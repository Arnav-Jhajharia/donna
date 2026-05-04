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

from datetime import datetime
from typing import Any, Literal


_MAX_REASON_LEN = 500

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
