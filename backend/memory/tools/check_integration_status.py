"""check_integration_status — fetch live ground truth for the user's
Composio integrations and merge with our local DB mirror.

Used when Donna needs to verify what's actually connected (e.g. the user
says "didn't work" / "still not connected" / "is gmail working"). Calls
Composio for the authoritative view, reconciles any drift into our local
``integrations`` table, and returns a per-toolkit summary.

Read-only by design — this tool may be called any number of times per
turn without idempotency concerns. It does WRITE state.* updates when
Composio truth disagrees with the local mirror, but those updates are
themselves idempotent (mark_connected / mark_revoked).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.integrations import composio_meta, state
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Read-only ground truth for the user's Composio integrations. Lists "
    "every connected_account on Composio's side AND merges with the "
    "local integrations DB so you can answer 'is gmail working?' or "
    "'why isn't my slack connected yet?' honestly. Reconciles any drift "
    "(e.g. user completed OAuth in browser but our watcher missed it) "
    "by upgrading local rows to connected when Composio says ACTIVE.\n\n"
    "Use when:\n"
    "  - the user says 'didn't work' / 'still broken' / 'retry' AFTER a "
    "previous connect_integration\n"
    "  - the user asks 'is X connected' / 'what integrations do I have'\n"
    "  - you need to verify ground truth before re-issuing a chain (NEVER "
    "re-issue connect_integration blindly — call this first)\n"
    "Do NOT use:\n"
    "  - on first connect (the [INTEGRATIONS] block already shows state)\n"
    "  - more than once per turn (the second call will return identical data)\n"
    "  - as a way to poll OAuth completion (the watcher does that)\n"
    "Returns: ``{toolkits: {<slug>: {status, connected_account_id, "
    "last_synced_at, error}}, summary: <one-line human read>}``."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "toolkits": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional filter — only check these toolkit slugs "
                "(e.g. ['gmail', 'slack']). Omit to check everything "
                "the user has touched."
            ),
        }
    },
}

# Same mapping used in connect_integration / oauth_watcher — kept local
# to avoid a circular import. Google toolkits surface under the friendly
# product names in the local DB (provider="google", product="gmail" etc).
_GOOGLE_TOOLKIT_TO_PRODUCT = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
}


def _provider_product(toolkit: str) -> tuple[str, str]:
    if toolkit in _GOOGLE_TOOLKIT_TO_PRODUCT:
        return "google", _GOOGLE_TOOLKIT_TO_PRODUCT[toolkit]
    return "composio", toolkit


def _local_toolkit(provider: str, product: str) -> str:
    """Reverse mapping — local row -> composio toolkit slug."""
    if provider == "google":
        for slug, prod in _GOOGLE_TOOLKIT_TO_PRODUCT.items():
            if prod == product:
                return slug
    return product


_STATUS_PRIORITY = {
    "ACTIVE": 0,        # most authoritative
    "INITIATED": 1,
    "PENDING": 1,
    "EXPIRED": 2,
    "FAILED": 3,
    "DELETED": 4,
}


async def _list_composio_accounts(user_id: str) -> dict[str, dict]:
    """Returns ``{toolkit_slug: {status, id}}`` from the live Composio API.

    Composio creates a NEW connected_account per ``connected_accounts.initiate``
    call, so a user who taps two chain URLs ends up with multiple rows
    per toolkit (one ACTIVE plus one INITIATED, or two INITIATED). When
    we render integration status we want the SINGLE most-authoritative
    row per toolkit — ACTIVE wins over INITIATED wins over EXPIRED, etc.
    The previous implementation was last-write-wins and silently
    reported INITIATED even when an ACTIVE row existed, which made
    reconcile decide nothing was connected.
    """
    try:
        composio = composio_meta._composio()
        listing = await asyncio.to_thread(
            composio.connected_accounts.list, user_ids=[user_id]
        )
    except Exception:
        logger.exception("check_integration_status: composio list failed")
        return {}
    items = listing.items if hasattr(listing, "items") else list(listing)
    out: dict[str, dict] = {}
    for ca in items:
        slug = getattr(getattr(ca, "toolkit", None), "slug", None)
        if not slug:
            continue
        status = (getattr(ca, "status", None) or "").upper()
        new = {"status": status, "id": getattr(ca, "id", None)}
        existing = out.get(slug)
        if existing is None:
            out[slug] = new
            continue
        # Prefer the entry with the lowest priority number (ACTIVE=0).
        # Unknown statuses fall to the bottom so a known status always
        # beats an unknown one.
        if _STATUS_PRIORITY.get(status, 99) < _STATUS_PRIORITY.get(
            existing["status"], 99
        ):
            out[slug] = new
    return out


# Toolkits whose connection should fire the gmail-driven bootstrap +
# proactive ping. Mirrors backend.integrations.oauth_watcher's set so
# every reconcile path makes the same decision.
_BOOTSTRAP_TOOLKITS: frozenset[str] = frozenset({
    "gmail", "googlecalendar", "googledrive"
})


async def _reconcile(
    user_id: str, toolkit: str, composio_view: dict | None
) -> bool:
    """If Composio says ACTIVE but local row isn't connected, upgrade.
    If Composio says EXPIRED/DELETED but local row says connected, mark
    revoked. No-op when local + remote agree.

    Returns True iff this call flipped a row pending/absent -> connected.
    Used by the caller to decide whether to spawn the bootstrap pipeline
    (the watcher / webhook would normally fire it, but this reconcile
    self-heals the case where neither path delivered)."""
    provider, product = _provider_product(toolkit)
    local = await state.get_integration_status(user_id, provider, product)
    remote_status = (composio_view or {}).get("status")
    remote_id = (composio_view or {}).get("id")

    if remote_status == "ACTIVE":
        if local is None or local.status != "connected":
            await state.upsert_pending(user_id, provider, product)
            await state.mark_connected(
                user_id, provider, product, connection_id=remote_id
            )
            logger.info(
                "check_integration_status: reconciled %s -> connected (was %s)",
                toolkit,
                getattr(local, "status", "absent"),
            )
            return True
        return False
    if remote_status in {"EXPIRED", "DELETED", "FAILED"}:
        if local is not None and local.status == "connected":
            await state.mark_revoked(user_id, provider, product)
            logger.info(
                "check_integration_status: reconciled %s -> revoked (composio=%s)",
                toolkit,
                remote_status,
            )


def _summary_line(toolkit_view: dict[str, dict]) -> str:
    """Compact human-readable summary so Donna can render without parsing."""
    if not toolkit_view:
        return "no integrations on file"
    parts = []
    for slug, info in toolkit_view.items():
        s = info["status"]
        if s == "connected":
            parts.append(f"{slug}=on")
        elif s == "pending":
            parts.append(f"{slug}=pending")
        elif s == "revoked":
            parts.append(f"{slug}=revoked")
        elif s == "absent":
            parts.append(f"{slug}=not_connected")
        else:
            parts.append(f"{slug}={s}")
    return ", ".join(parts)


async def reconcile_with_composio(
    user_id: str, toolkits: list[str] | None = None
) -> dict[str, dict]:
    """Side-effecting reconcile: fetch Composio truth, upgrade pending->
    connected and connected->revoked rows in our DB to match. Returns the
    raw composio view (toolkit_slug -> {status, id}) for callers that
    want to render it. Used both by the on-demand tool and by the
    per-turn gate in donna_runtime.context_builder.

    Self-heals the bootstrap + notify paths: when reconcile discovers a
    toolkit just went ACTIVE (because the watcher / webhook never fired,
    e.g. composio webhook delivery failed or the watcher's asyncio task
    was killed by a uvicorn reload), it (a) fires the immediate
    "<toolkit> connected" ping so the user actually hears about it, and
    (b) for google toolkits spawns run_bootstrap_async so the gmail
    ingest pipeline still runs.
    """
    composio_view = await _list_composio_accounts(user_id)
    if toolkits:
        wanted = {t.strip() for t in toolkits if t and t.strip()}
        composio_view = {k: v for k, v in composio_view.items() if k in wanted}
    newly_connected: list[str] = []
    for toolkit, info in composio_view.items():
        was_flipped = await _reconcile(user_id, toolkit, info)
        if was_flipped:
            newly_connected.append(toolkit)

    if newly_connected:
        # Immediate-confirm ping. Dedupe is per-stage so this doesn't
        # clash with the post-bootstrap message the gmail pipeline sends.
        try:
            import asyncio

            from backend.integrations.notify import (
                STAGE_CONNECTED,
                notify_integration_complete,
            )

            asyncio.create_task(
                notify_integration_complete(
                    user_id, newly_connected, stage=STAGE_CONNECTED
                )
            )
        except Exception:
            logger.exception(
                "check_integration_status: notify spawn failed user=%s",
                user_id,
            )

    newly_connected_google = [
        t for t in newly_connected if t in _BOOTSTRAP_TOOLKITS
    ]
    if newly_connected_google:
        try:
            import asyncio

            from api.composio_webhook import run_bootstrap_async

            asyncio.create_task(run_bootstrap_async(user_id))
            logger.info(
                "check_integration_status: spawned bootstrap user=%s "
                "newly_connected=%s",
                user_id, newly_connected_google,
            )
        except Exception:
            logger.exception(
                "check_integration_status: bootstrap spawn failed user=%s",
                user_id,
            )
    return composio_view


@instrument_memory_op("integrations.status")
async def check_integration_status(
    user_id: str, toolkits: list[str] | None = None
) -> dict[str, Any]:
    """Live ground-truth fetch + local reconcile. See module docstring."""
    composio_view = await _list_composio_accounts(user_id)
    local_rows = await state.list_user_integrations(user_id)

    # Build the union of toolkits to inspect: explicit filter wins,
    # otherwise we look at every toolkit either side has heard of.
    seen: set[str] = set()
    for slug in composio_view.keys():
        seen.add(slug)
    for row in local_rows:
        seen.add(_local_toolkit(row.provider, row.product))

    if toolkits:
        wanted = set(t.strip() for t in toolkits if t and t.strip())
        seen = {t for t in seen if t in wanted}
        # Include any explicitly-requested toolkit that neither side knows
        # about — Donna gets back "absent" instead of nothing.
        seen |= wanted

    results: dict[str, dict] = {}
    newly_connected: list[str] = []
    for toolkit in sorted(seen):
        composio_info = composio_view.get(toolkit)
        # Reconcile drift before reading local state again.
        if composio_info is not None:
            was_flipped = await _reconcile(user_id, toolkit, composio_info)
            if was_flipped:
                newly_connected.append(toolkit)
        provider, product = _provider_product(toolkit)
        local = await state.get_integration_status(user_id, provider, product)
        if local is None and composio_info is None:
            results[toolkit] = {
                "status": "absent",
                "connected_account_id": None,
                "last_synced_at": None,
                "error": None,
            }
            continue
        results[toolkit] = {
            "status": local.status if local else "absent",
            "connected_account_id": (
                local.composio_connection_id if local else None
            ),
            "last_synced_at": (
                local.last_synced_at.isoformat()
                if local and local.last_synced_at
                else None
            ),
            "error": local.last_error if local else None,
        }

    # Self-heal stage 1: notify the user that any newly discovered
    # connections actually landed. This catches the (real) case where
    # the watcher died and the webhook 404'd, so reconcile is the only
    # path that knew the connection went ACTIVE — without this fire,
    # the user gets silence.
    if newly_connected:
        try:
            import asyncio

            from backend.integrations.notify import (
                STAGE_CONNECTED,
                notify_integration_complete,
            )

            asyncio.create_task(
                notify_integration_complete(
                    user_id, newly_connected, stage=STAGE_CONNECTED
                )
            )
        except Exception:
            logger.exception(
                "check_integration_status: notify spawn failed user=%s",
                user_id,
            )

    # Self-heal stage 2: if reconcile just discovered google toolkits
    # going ACTIVE, kick the bootstrap so email_messages get populated
    # and Donna has data to read from. Bootstrap fires its own
    # post-success notify (stage=bootstrapped) — independent of stage 1.
    newly_connected_google = [
        t for t in newly_connected if t in _BOOTSTRAP_TOOLKITS
    ]
    if newly_connected_google:
        try:
            import asyncio

            from api.composio_webhook import run_bootstrap_async

            asyncio.create_task(run_bootstrap_async(user_id))
            logger.info(
                "check_integration_status: spawned bootstrap user=%s "
                "newly_connected=%s",
                user_id, newly_connected_google,
            )
        except Exception:
            logger.exception(
                "check_integration_status: bootstrap spawn failed user=%s",
                user_id,
            )

    return {
        "toolkits": results,
        "summary": _summary_line(results),
    }
