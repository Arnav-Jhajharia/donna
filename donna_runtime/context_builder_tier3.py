"""Tier 3 fat-contract context builder.

Renders the 11 blocks from the spec into one user-message string. The
LLM call lives elsewhere (donna_runtime/brain.py); this module is pure
formatting + composition over already-fetched data.

The block contents are computed by the dispatcher's pre-build step and
passed in as strings, so this module stays free of DB / network deps
and is trivially testable.

Blocks rendered:
  1. WHY YOU'RE AWAKE        (from event + escalation_reason)
  2. USER MODEL              (precomputed string)
  3. THE QUEUED THING        (precomputed string)
  4. THE EVENT PAYLOAD       (from event)
  5. TIER 2                  (from JudgeResult)
  6. DAY VIEW                (precomputed string)
  7. PRIOR TOUCHES           (precomputed string)
  8. USER STATE NOW          (precomputed string)
  9. PENDING NOTES           (precomputed string)
  10. FRESH SIGNAL           (precomputed string, conditional)
  11. AVAILABLE TOOLS        (lives in the system prompt, not user msg)
"""
from __future__ import annotations

from proactive.events import EscalationReason, ProactiveEvent
from proactive.judge import JudgeResult


_PAYLOAD_VALUE_MAX_CHARS = 600


def build_tier3_user_message(
    *,
    event: ProactiveEvent,
    judge: JudgeResult,
    escalation_reason: EscalationReason,
    user_model_block: str,
    queued_thing_block: str,
    day_view_block: str,
    prior_touches_block: str,
    user_state_block: str,
    pending_notes_block: str,
    fresh_signal_block: str | None,
) -> str:
    """Compose the Tier 3 USER message from pre-built blocks.

    Block 1 (why you're awake) and block 4 (event payload) are rendered
    inline from the event + escalation_reason. Block 5 (Tier 2 output)
    is rendered from JudgeResult. The rest come in as strings.
    """
    parts: list[str] = []

    # Block 1 — WHY YOU'RE AWAKE
    parts.append(
        f"# WHY YOU'RE AWAKE\n"
        f"escalation_reason: {escalation_reason}\n"
        f"speech_act: {event.speech_act}\n"
        f"source: {event.source}"
    )

    # Block 2 — USER MODEL (precomputed)
    parts.append(f"# USER MODEL\n{user_model_block.strip()}")

    # Block 3 — THE QUEUED THING (precomputed spec render)
    parts.append(f"# THE QUEUED THING\n{queued_thing_block.strip()}")

    # Block 4 — THE EVENT PAYLOAD (rendered from event)
    payload_lines = [f"source_ref: {event.source_ref}", f"topic_key: {event.topic_key}"]
    for k, v in (event.payload or {}).items():
        rendered = str(v)
        if len(rendered) > _PAYLOAD_VALUE_MAX_CHARS:
            rendered = rendered[:_PAYLOAD_VALUE_MAX_CHARS] + " …"
        payload_lines.append(f"{k}: {rendered}")
    if event.signals:
        payload_lines.append("signals:")
        for k, v in event.signals.items():
            payload_lines.append(f"  {k}: {v}")
    parts.append("# THE EVENT PAYLOAD\n" + "\n".join(payload_lines))

    # Block 5 — TIER 2 (the hint, not the constraint)
    tier2_lines = [f"action: {judge.action}"]
    if judge.register is not None:
        tier2_lines.append(f"register: {judge.register}")
    tier2_lines.extend([
        f"draft: {judge.draft or '(none)'}",
        f"tie_in: {list(judge.tie_in) if judge.tie_in else '[]'}",
        f"needs_tools: {judge.needs_tools}",
        f"reasoning: {judge.reasoning or '(none)'}",
    ])
    if judge.channel_hint:
        tier2_lines.append(f"channel_hint: {judge.channel_hint}")
    if judge.reclassify_speech_act:
        tier2_lines.append(f"reclassify_speech_act: {judge.reclassify_speech_act}")
    parts.append("# TIER 2\n" + "\n".join(tier2_lines))

    # Block 6 — DAY VIEW (precomputed)
    parts.append(f"# DAY VIEW\n{day_view_block.strip()}")

    # Block 7 — PRIOR TOUCHES (precomputed)
    parts.append(f"# PRIOR TOUCHES\n{prior_touches_block.strip()}")

    # Block 8 — USER STATE NOW (precomputed)
    parts.append(f"# USER STATE NOW\n{user_state_block.strip()}")

    # Block 9 — PENDING NOTES (precomputed)
    parts.append(f"# PENDING NOTES\n{pending_notes_block.strip()}")

    # Block 10 — FRESH SIGNAL (conditional)
    if fresh_signal_block and fresh_signal_block.strip():
        parts.append(f"# FRESH SIGNAL\n{fresh_signal_block.strip()}")

    # Block 11 — TOOLS lives in the system prompt (not user msg).

    return "\n\n".join(parts)


import logging

logger = logging.getLogger(__name__)


_PLACEHOLDER_PREFIX = "(phase 2a — degraded fallback)"


async def load_user_model_block_for_tier3(*, user_id: str) -> str:
    """Render the USER MODEL block for the Tier 3 input contract.

    Reuses the existing reactive helper. On any failure, returns a
    placeholder so the dispatcher never blocks.
    """
    try:
        from donna_runtime.context_builder import load_user_model_block

        block = await load_user_model_block(user_id) or ""
        if not block.strip():
            return f"{_PLACEHOLDER_PREFIX} no user model loaded"
        return block.strip()
    except Exception:
        logger.exception(
            "tier3 block: USER MODEL load failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} user model unavailable"


async def load_pending_notes_block(*, user_id: str) -> str:
    """Render the PENDING NOTES block from active pending_proactive_notes."""
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import PendingProactiveNote
    except Exception:
        logger.exception("tier3 block: pending_notes imports failed")
        return f"{_PLACEHOLDER_PREFIX} pending notes unavailable"

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(PendingProactiveNote)
                    .where(PendingProactiveNote.user_id == user_id)
                    .where(PendingProactiveNote.status == "pending")
                    .order_by(PendingProactiveNote.created_at.desc())
                    .limit(20)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "tier3 block: pending_notes query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} pending notes query failed"

    if not rows:
        return "no pending notes."

    lines = []
    for row in rows:
        # Compact one-line per note. Truncate long drafts to keep prompt tight.
        draft = (getattr(row, "draft_text", None) or getattr(row, "draft", None) or "")[:160]
        topic = getattr(row, "topic_key", None) or "(no topic)"
        lines.append(f"- {topic} — {draft}")
    return "\n".join(lines)
