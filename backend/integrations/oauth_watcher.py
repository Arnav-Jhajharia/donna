"""Background poller for OAuth completion + auto-bootstrap.

After ``connect_integration`` spawns OAuth, this watcher polls Composio
until the requested toolkits flip to ACTIVE, then mirrors the connection
state in our DB and fires ``run_bootstrap_async`` so gmail/calendar/drive
ingestion kicks off without waiting for Composio's webhook.

Designed to run as a fire-and-forget ``asyncio.create_task`` from the
PostToolUse hook. Catches and logs all exceptions — never raises.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from backend.integrations import composio_meta, state

logger = logging.getLogger(__name__)

# Maps Composio toolkit slug -> our local product name.
_TOOLKIT_TO_PRODUCT = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
}

POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 10 * 60  # 10 min OAuth window


async def _list_active_connections(
    user_id: str, toolkits: list[str]
) -> dict[str, str]:
    """Returns ``{toolkit_slug: connected_account_id}`` for ACTIVE only.

    Composio's SDK is synchronous, so we offload the network call to a
    thread to avoid stalling the event loop.
    """
    composio = composio_meta._composio()
    listing = await asyncio.to_thread(
        composio.connected_accounts.list,
        user_ids=[user_id],
        toolkit_slugs=toolkits,
    )
    items = listing.items if hasattr(listing, "items") else list(listing)
    out: dict[str, str] = {}
    for ca in items:
        if (getattr(ca, "status", None) or "").upper() != "ACTIVE":
            continue
        slug = getattr(getattr(ca, "toolkit", None), "slug", None)
        if slug in toolkits:
            out[slug] = ca.id
    return out


async def watch_google_oauth_and_bootstrap(
    *,
    user_id: str,
    toolkits: Iterable[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: int = POLL_INTERVAL_SECONDS,
) -> None:
    """Poll Composio until all toolkits ACTIVE, then mark DB + fire bootstrap.

    Fire-and-forget: never raises. If the deadline lapses before any
    connection becomes ACTIVE we log a warning and return without firing
    bootstrap. Partial completion (some active, some not) still fires
    bootstrap because the active connections are useful on their own.
    """
    requested = [t for t in toolkits if t in _TOOLKIT_TO_PRODUCT]
    if not requested:
        return

    try:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        active: dict[str, str] = {}
        # Always poll at least once even if timeout==0 — the OAuth chain
        # may already have completed by the time the watcher runs.
        while True:
            active = await _list_active_connections(user_id, requested)
            if all(t in active for t in requested):
                break
            if asyncio.get_event_loop().time() >= deadline:
                break
            await asyncio.sleep(poll_interval)

        if not active:
            logger.warning(
                "oauth_watcher: timeout user=%s toolkits=%s — no active connections",
                user_id,
                requested,
            )
            return

        # Mark each connected toolkit in our DB.
        for toolkit, ca_id in active.items():
            product = _TOOLKIT_TO_PRODUCT[toolkit]
            try:
                await state.upsert_pending(user_id, "google", product)
                await state.mark_connected(
                    user_id, "google", product, connection_id=ca_id
                )
            except Exception:
                logger.exception(
                    "oauth_watcher: mark_connected failed user=%s product=%s",
                    user_id,
                    product,
                )

        # Fire bootstrap (in-process — already async).
        try:
            from api.composio_webhook import run_bootstrap_async

            await run_bootstrap_async(user_id)
            logger.info(
                "oauth_watcher: bootstrap fired user=%s toolkits=%s",
                user_id,
                list(active.keys()),
            )
        except Exception:
            logger.exception(
                "oauth_watcher: bootstrap fire failed user=%s", user_id
            )
    except Exception:
        logger.exception("oauth_watcher: unexpected failure user=%s", user_id)
