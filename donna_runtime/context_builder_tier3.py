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

from typing import Literal

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


EscalationReason = Literal[
    "needs_tools",
    "empty_draft",
    "validator_fail",
    "stakes_aware",
    "hold_ambiguity",
    "tier2_failed",
]


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
    tier2_lines = [
        f"action: {judge.action}",
        f"register: {judge.register or 'n/a'}",
        f"draft: {judge.draft or '(none)'}",
        f"tie_in: {list(judge.tie_in) if judge.tie_in else '[]'}",
        f"needs_tools: {judge.needs_tools}",
        f"reasoning: {judge.reasoning or '(none)'}",
    ]
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
