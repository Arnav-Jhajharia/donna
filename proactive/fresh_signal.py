"""Conditional pre-fetch of fresh signal for Tier 3 input contract.

Only fetches when speech_act ∈ {heads_up, now_the_moment} AND the event
is older than ``_STALE_THRESHOLD_MINUTES``. Other speech acts don't gain
from re-fetching: dont_forget reminders are time-anchored, thought_youd_want
hits are already fresh by construction, i_noticed is state-based not
event-based.

Per-source fetchers live here. Each returns a dict with at least:
    { "status": "ok" | "no_fetcher" | "degraded",
      "result": <source-specific>,
      "delta_from_original": <human readable>,
      "fetched_at": ISO timestamp }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from proactive.events import ProactiveEvent


logger = logging.getLogger(__name__)

_STALE_THRESHOLD_MINUTES = 60
_PREFETCH_ACTS = {"heads_up", "now_the_moment"}


def should_prefetch(event: ProactiveEvent) -> bool:
    """True iff fresh signal should be re-fetched at Tier 3 context build."""
    if event.speech_act not in _PREFETCH_ACTS:
        return False
    age_minutes = float(event.signals.get("event_age_minutes") or 0.0)
    return age_minutes >= _STALE_THRESHOLD_MINUTES


async def fetch_for_event(event: ProactiveEvent) -> dict[str, Any]:
    """Return a fresh-signal payload for the given event.

    Caller MUST check ``should_prefetch(event)`` first; this function
    runs the actual fetch. Per-source fetchers are dispatched off
    ``event.source``.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        if event.source == "email":
            return await _fetch_email(event, fetched_at)
        if event.source == "calendar":
            return await _fetch_calendar(event, fetched_at)
        if event.source == "system_b_web":
            return await _fetch_system_b(event, fetched_at)
        if event.source == "attention_fire":
            return await _fetch_attention(event, fetched_at)
        return {"status": "no_fetcher", "fetched_at": fetched_at}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.exception("fresh_signal: fetch raised source=%s", event.source)
        return {
            "status": "degraded",
            "fetched_at": fetched_at,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# --- Per-source stubs -------------------------------------------------------
# Each returns a placeholder result for Phase 1. Real implementations land
# alongside the System B fold-in (Phase 2) and the Tier 2 / cutover work.


async def _fetch_email(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    # Real impl in Phase 2: re-fetch the gmail thread state.
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — gmail re-fetch not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_calendar(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — calendar re-fetch not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_system_b(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — Exa re-search not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_attention(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — attention dry_run re-execution not yet wired"},
        "delta_from_original": "stub",
    }
