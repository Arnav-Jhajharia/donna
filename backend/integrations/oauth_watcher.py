"""Background poller for OAuth completion + auto-bootstrap.

After ``connect_integration`` spawns OAuth, this watcher polls Composio
until the requested toolkits flip to ACTIVE, then mirrors the connection
state in our DB. When any of the google toolkits (gmail / calendar /
drive) lands, the watcher fires ``run_bootstrap_async`` so the smart
gmail-driven bootstrap pipeline (today_dense + 30d_important +
90d_aggregates + biography_synthesis) kicks off without waiting for
Composio's webhook.

Designed to run as a fire-and-forget ``asyncio.create_task`` from the
PostToolUse hook. Catches and logs all exceptions — never raises.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from backend.integrations import composio_meta, state

logger = logging.getLogger(__name__)

# Composio toolkit slug -> (provider, product) for the integrations table.
# Google toolkits keep ``provider="google"`` so the existing
# [INTEGRATIONS] line format and downstream typed tools stay coherent.
# Everything else lands as ``provider="composio"`` with the toolkit slug
# as the product.
_GOOGLE_TOOLKIT_TO_PRODUCT: dict[str, str] = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
}

# Subset of toolkits whose connection should trigger the gmail-driven
# bootstrap pipeline (run_bootstrap_async). Connecting slack does NOT.
_BOOTSTRAP_TOOLKITS: frozenset[str] = frozenset({
    "gmail", "googlecalendar", "googledrive"
})

POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 10 * 60  # 10 min OAuth window


def _provider_product(toolkit: str) -> tuple[str, str]:
    if toolkit in _GOOGLE_TOOLKIT_TO_PRODUCT:
        return "google", _GOOGLE_TOOLKIT_TO_PRODUCT[toolkit]
    return "composio", toolkit


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


async def watch_oauth_and_bootstrap(
    *,
    user_id: str,
    toolkits: Iterable[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: int = POLL_INTERVAL_SECONDS,
) -> None:
    """Poll Composio until all toolkits ACTIVE, then mark DB + (maybe) bootstrap.

    Fire-and-forget: never raises. If the deadline lapses before any
    connection becomes ACTIVE we log a warning and return without firing
    bootstrap. Partial completion (some active, some not) still marks
    the active ones and fires bootstrap when a google toolkit is in the
    active set.
    """
    requested = [t for t in toolkits if t]
    if not requested:
        return

    logger.info(
        "oauth_watcher: started user=%s toolkits=%s timeout=%ds",
        user_id[:8], requested, timeout_seconds,
    )

    try:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        active: dict[str, str] = {}
        poll_count = 0
        # Always poll at least once even if timeout==0 — the OAuth chain
        # may already have completed by the time the watcher runs.
        while True:
            active = await _list_active_connections(user_id, requested)
            poll_count += 1
            if all(t in active for t in requested):
                logger.info(
                    "oauth_watcher: all active user=%s toolkits=%s polls=%d",
                    user_id[:8], list(active.keys()), poll_count,
                )
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
            provider, product = _provider_product(toolkit)
            try:
                await state.upsert_pending(user_id, provider, product)
                await state.mark_connected(
                    user_id, provider, product, connection_id=ca_id
                )
            except Exception:
                logger.exception(
                    "oauth_watcher: mark_connected failed user=%s toolkit=%s",
                    user_id,
                    toolkit,
                )

        # Fire bootstrap only when at least one google toolkit went ACTIVE.
        # Slack/notion/etc. don't get a bootstrap pass — that algorithm
        # is gmail-specific.
        google_active = [t for t in active if t in _BOOTSTRAP_TOOLKITS]
        non_google_active = [t for t in active if t not in _BOOTSTRAP_TOOLKITS]

        # Immediate-confirm ping for EVERY toolkit that just landed —
        # google ones get the post-bootstrap follow-up later but should
        # still get the immediate confirm so the user isn't staring at
        # silence between the OAuth tap and the bootstrap finishing.
        if active:
            try:
                from backend.integrations.notify import (
                    STAGE_CONNECTED,
                    notify_integration_complete,
                )

                await notify_integration_complete(
                    user_id, list(active.keys()), stage=STAGE_CONNECTED
                )
            except Exception:
                logger.exception(
                    "oauth_watcher: notify failed user=%s", user_id
                )

        # Drain any pending integration intents whose toolkit dependencies
        # are now all met. This is the resume-after-OAuth path: the user
        # asked for something that needed gmail, we sent them the link, they
        # tapped — now we answer the original ask without waiting for them
        # to re-prompt.
        for toolkit in active:
            try:
                from backend.integrations.pending_intents import drain_for_toolkit
                fired = await drain_for_toolkit(user_id, toolkit)
                if fired:
                    logger.info(
                        "oauth_watcher: drained %d pending intents user=%s toolkit=%s",
                        fired, user_id[:8], toolkit,
                    )
            except Exception:
                logger.exception(
                    "oauth_watcher: drain failed user=%s toolkit=%s",
                    user_id, toolkit,
                )

        if not google_active:
            logger.info(
                "oauth_watcher: connections active user=%s toolkits=%s "
                "(no google toolkit — skipping bootstrap)",
                user_id,
                list(active.keys()),
            )
            return

        # Google toolkits go through bootstrap, which itself fires the
        # post-bootstrap notify with the "read through your inbox" copy.
        try:
            from api.composio_webhook import run_bootstrap_async

            await run_bootstrap_async(user_id)
            logger.info(
                "oauth_watcher: bootstrap fired user=%s google_toolkits=%s",
                user_id,
                google_active,
            )
        except Exception:
            logger.exception(
                "oauth_watcher: bootstrap fire failed user=%s", user_id
            )
    except Exception:
        logger.exception("oauth_watcher: unexpected failure user=%s", user_id)


# Back-compat alias. Existing callers (including older trace data and any
# imports we missed) keep working; new code should use
# ``watch_oauth_and_bootstrap`` directly.
watch_google_oauth_and_bootstrap = watch_oauth_and_bootstrap
