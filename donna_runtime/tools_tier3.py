"""Tier 3 tool palette — fat-contract editorial brain.

Six tools, narrowly scoped:
    Reads:  quick_check, read_external
    Writes: send_burst, reshape_attention, kill_attention, skip

Every Tier 3 turn must call exactly one of {send_burst, skip,
reshape_attention, kill_attention} as the terminator. The harness
forces skip(reason="max_turns_exceeded") if turn 3 doesn't terminate.

Phase 1 implementation: tool bodies return outcome dicts that the
dispatcher routes downstream. Side effects (DB writes, WhatsApp sends,
schedule cancels) live in the dispatcher's outcome handler — keeps
tools pure and testable.

Tasks 7 (send_burst) and 8 (quick_check, read_external) extend this
file. Task 6 ships only the three terminators below.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

_MAX_REASON_LEN = 500
_QUICK_CHECK_MAX_RESULTS = 5
_READ_EXTERNAL_SOURCES = {
    "gmail_thread",
    "calendar_event",
    "exa_url",
    "person_recent_chat",
}

# ---- terminators -----------------------------------------------------------


async def skip(reason: str) -> dict[str, Any]:
    """Explicit silence. First-class outcome.

    USE WHEN: fresh signal shows the moment is dead, the topic is
              already covered, or your editorial read is that this fire
              would degrade trust.
    DO NOT USE: when you'd rather hold (use send_burst with push=False).
    """
    if not reason or not reason.strip():
        raise ValueError("skip requires a reason (one short sentence)")
    return {"action": "skip", "reason": reason.strip()[:_MAX_REASON_LEN]}


async def kill_attention(*, attention_id: str, reason: str) -> dict[str, Any]:
    """Terminate a live attention. Sets status=killed, cancels future
    schedule rows. Permanent.

    USE WHEN: fresh signal shows the user already did the thing, the
              moment is permanently gone, or the spec was wrong from
              the start.
    DO NOT USE: for transient stale (use reshape_attention with
                next_fire_at instead).
    """
    attention_id = attention_id.strip() if attention_id else ""
    if not attention_id:
        raise ValueError("attention_id is required")
    if not reason or not reason.strip():
        raise ValueError("reason is required (one short sentence)")
    return {
        "action": "kill",
        "attention_id": attention_id,
        "reason": reason.strip()[:_MAX_REASON_LEN],
    }


async def reshape_attention(
    *,
    attention_id: str,
    next_fire_at: datetime | None = None,
    surface_level: Literal["silent", "digest", "notify", "urgent"] | None = None,
    cadence_change: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Modify the live attention spec without firing.

    USE WHEN: world changed but the spec is still useful (push to
              tomorrow, downgrade urgency, fold cadence).
    DO NOT USE: when the right action is to fire now (use send_burst), or
                when the spec is permanently moot (use kill_attention).
    """
    attention_id = attention_id.strip() if attention_id else ""
    if not attention_id:
        raise ValueError("attention_id is required")
    if next_fire_at is None and surface_level is None and not cadence_change:
        raise ValueError(
            "reshape_attention needs at least one change: next_fire_at, "
            "surface_level, or cadence_change"
        )
    reshape_kwargs: dict[str, Any] = {}
    if next_fire_at is not None:
        reshape_kwargs["next_fire_at"] = next_fire_at.isoformat()
    if surface_level is not None:
        reshape_kwargs["surface_level"] = surface_level
    if cadence_change:
        reshape_kwargs["cadence_change"] = cadence_change
    return {
        "action": "reshape",
        "attention_id": attention_id,
        "reshape_kwargs": reshape_kwargs,
    }


async def send_burst(
    *,
    messages: list[dict[str, Any]],
    push: bool = True,
    surface_at: Literal["next_user_touch", "morning_brief"] | None = None,
) -> dict[str, Any]:
    """Ship the proactive message. Channel is inline.

    Quadrants:
      push=True,  surface_at=None         -> WhatsApp ping + chat_messages
      push=False, surface_at=None         -> ambient (chat_messages only)
      push=False, surface_at="next_user_touch" -> pending_proactive_notes,
                                                 surfaces in next reactive turn
      push=False, surface_at="morning_brief"   -> pending note tagged for
                                                  tomorrow's morning brief

    USE: to actually ship (or hold).
    DO NOT USE: when fresh signal shows the moment is dead — use skip.

    NOTE: surface_at is meaningful only with push=False. push=True with
    surface_at set raises — pushing means the user gets it now, holding
    is a contradiction.
    """
    if not messages:
        raise ValueError("messages list must not be empty")
    if push and surface_at is not None:
        raise ValueError(
            "surface_at requires push=False (you can't push and hold at "
            "the same time)"
        )
    return {
        "action": "ship",
        "messages": messages,
        "push": push,
        "surface_at": surface_at,
    }


# ---- read tools ------------------------------------------------------------


class _ExaSearchDegraded(Exception):
    """Raised when the Exa search call could not be completed (import
    failure, missing key, network error, etc.). The public tool layer
    catches this and surfaces status='degraded' so the brain can
    distinguish 'no hits' from 'tool failed'."""


async def _exa_search_for_quick_check(
    *, query: str, num_results: int
) -> list[dict[str, Any]]:
    """Indirection for monkeypatching in tests + isolating the Exa client.

    Returns a list of simplified hit dicts with title/url/excerpt.
    Raises _ExaSearchDegraded when Exa cannot be reached (no key, import
    failure, runtime exception). An empty list means Exa returned zero
    matches — that is a valid result, not a failure.
    """
    try:
        from backend.web.client import exa_search, have_exa_key
    except Exception as exc:
        logger.exception("quick_check: exa client import failed")
        raise _ExaSearchDegraded("exa_client_import_failed") from exc
    if not have_exa_key():
        logger.warning("quick_check: no EXA_API_KEY")
        raise _ExaSearchDegraded("missing_exa_api_key")
    try:
        response = await exa_search(query=query, num_results=num_results)
    except Exception as exc:
        logger.exception("quick_check: exa_search raised")
        raise _ExaSearchDegraded(f"exa_search_raised:{type(exc).__name__}") from exc
    raw_results = response.get("results", []) if isinstance(response, dict) else []
    return [
        {
            "title": (item.get("title") or "")[:200],
            "url": item.get("url") or "",
            "excerpt": (item.get("text") or item.get("excerpt") or "")[:400],
        }
        for item in (raw_results or [])
    ]


async def quick_check(
    *,
    question: str,
    max_results: int = 3,
) -> dict[str, Any]:
    """One-shot web search to verify a specific claim or fetch a focused fact.

    USE WHEN: the event makes a factual claim that needs verification, OR
              thought_youd_want needs a freshness check.
    DO NOT USE: for general research or exploration. This is verification,
                not curiosity.
    HARD LIMIT: one call per turn. The harness rejects a second call.
    Cost: ~$0.005, ~1-2s.

    Returns one of:
      {status: "ok",         results: [...], ...}  hits returned
      {status: "no_results", results: [],    ...}  Exa called, zero hits
      {status: "degraded",   results: [],    error: <reason>, ...}
                                                   Exa unreachable
    """
    if not question or not question.strip():
        raise ValueError("question is required")
    if max_results <= 0 or max_results > _QUICK_CHECK_MAX_RESULTS:
        raise ValueError(
            f"max_results must be 1..{_QUICK_CHECK_MAX_RESULTS}; got {max_results}"
        )
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        results = await _exa_search_for_quick_check(
            query=question.strip(), num_results=max_results
        )
    except _ExaSearchDegraded as exc:
        return {
            "status": "degraded",
            "question": question.strip(),
            "results": [],
            "error": str(exc),
            "fetched_at": fetched_at,
        }
    return {
        "status": "ok" if results else "no_results",
        "question": question.strip(),
        "results": results,
        "fetched_at": fetched_at,
    }


async def read_external(
    *,
    source: Literal[
        "gmail_thread", "calendar_event", "exa_url", "person_recent_chat"
    ],
    ref: str,
) -> dict[str, Any]:
    """Fresh state of one specific external resource by identifier.

    USE WHEN: need fresh state of something specifically referenced by id,
              and that exact resource isn't in the pre-fetched fresh_signal
              block.
    DO NOT USE: when pre-fetched fresh_signal already has what you need.
    Cost: source-specific, ~0.5-2s.
    """
    if source not in _READ_EXTERNAL_SOURCES:
        raise ValueError(
            f"source must be one of {_READ_EXTERNAL_SOURCES}; got {source!r}"
        )
    if not ref:
        raise ValueError("ref is required")
    # Phase 1 stub. Real per-source fetchers land with the System B
    # fold-in. We return note="stub" (not human-readable prose) so the
    # LLM doesn't try to interpret a free-form engineering message.
    return {
        "status": "no_fetcher",
        "source": source,
        "ref": ref,
        "note": "stub",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
