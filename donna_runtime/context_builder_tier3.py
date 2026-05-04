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


async def load_day_view_block(*, user_id: str) -> str:
    """Render the DAY VIEW block.

    Compact, fits in a few hundred tokens. Pulls from:
      - chat_messages today (Donna's outbound + user's inbound, with
        timestamps and short snippets)
      - proactive_dispatch_telemetry today (proactive fires this user
        already received, with topic_key + speech_act + draft)
      - schedule_fires today via DonnaSchedule.fired_at

    Degrades gracefully on any failure.
    """
    try:
        from sqlalchemy import and_, or_, select

        from backend.db.session import async_session
        from db.models import (
            ChatMessage,
            DonnaSchedule,
            ProactiveDispatchTelemetry,
        )
    except Exception:
        logger.exception("tier3 block: day_view imports failed")
        return f"{_PLACEHOLDER_PREFIX} day view unavailable"

    from datetime import datetime, timedelta

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    chat_lines: list[str] = []
    fires_today: list[str] = []
    schedule_fires: list[str] = []

    try:
        async with async_session() as session:
            # Chat messages today
            chat_rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.created_at >= today_start)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(40)
                )
            ).scalars().all()

            for cm in chat_rows:
                role = getattr(cm, "role", "") or ""
                ts = getattr(cm, "created_at", None)
                ts_str = ts.strftime("%H:%M") if ts else "??:??"
                content = (getattr(cm, "content", None) or "")[:60]
                chat_lines.append(f"  {ts_str} [{role}] {content}")

            # Proactive fires today
            fire_rows = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.event_at >= today_start)
                    .order_by(ProactiveDispatchTelemetry.event_at.asc())
                )
            ).scalars().all()

            for fr in fire_rows:
                draft = (getattr(fr, "tier2_draft", None) or "")[:60]
                fires_today.append(
                    f"  {fr.speech_act} on {fr.topic_key} → {draft}"
                )

            # Schedule fires today
            sched_rows = (
                await session.execute(
                    select(DonnaSchedule)
                    .where(DonnaSchedule.user_id == user_id)
                    .where(DonnaSchedule.fired_at >= today_start)
                    .order_by(DonnaSchedule.fired_at.asc())
                    .limit(20)
                )
            ).scalars().all()

            for sr in sched_rows:
                ts = getattr(sr, "fired_at", None)
                ts_str = ts.strftime("%H:%M") if ts else "??:??"
                schedule_fires.append(f"  {ts_str} fired sched {sr.id[:8]}")
    except Exception:
        logger.exception(
            "tier3 block: day_view query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} day view query failed"

    parts: list[str] = []
    parts.append(f"today (UTC): {today_start.date().isoformat()}")
    parts.append(f"proactive fires today: {len(fires_today)}")
    if fires_today:
        parts.extend(fires_today)
    parts.append(f"schedule fires today: {len(schedule_fires)}")
    if schedule_fires:
        parts.extend(schedule_fires)
    parts.append(f"chat messages today: {len(chat_lines)}")
    if chat_lines:
        parts.extend(chat_lines[-10:])  # last 10 messages only
    return "\n".join(parts)


async def load_prior_touches_block(
    *,
    user_id: str,
    topic_key: str,
    lookback_days: int = 7,
) -> str:
    """Render the PRIOR TOUCHES block.

    Surfaces:
      - Most recent proactive fire on this topic_key (or any topic if
        none specifically) within lookback_days.
      - The user's response within 1h, if available (Phase 2: today
        we don't have a join from telemetry to chat replies; fallback
        to 'no response captured').

    Tells the brain whether to double-tap. Degrades gracefully.
    """
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import ProactiveDispatchTelemetry
    except Exception:
        logger.exception("tier3 block: prior_touches imports failed")
        return f"{_PLACEHOLDER_PREFIX} prior touches unavailable"

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    try:
        async with async_session() as session:
            # Most recent fire on this topic
            on_topic = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.topic_key == topic_key)
                    .where(ProactiveDispatchTelemetry.event_at >= cutoff)
                    .order_by(ProactiveDispatchTelemetry.event_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            # Most recent fire any topic (for double-tap risk)
            any_topic = (
                await session.execute(
                    select(ProactiveDispatchTelemetry)
                    .where(ProactiveDispatchTelemetry.user_id == user_id)
                    .where(ProactiveDispatchTelemetry.event_at >= cutoff)
                    .order_by(ProactiveDispatchTelemetry.event_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception(
            "tier3 block: prior_touches query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} prior touches query failed"

    parts: list[str] = []
    if on_topic:
        delta = datetime.utcnow() - on_topic.event_at
        hours = int(delta.total_seconds() / 3600)
        draft = (on_topic.tier2_draft or "")[:80]
        parts.append(
            f"on this topic ({topic_key}): last fire {hours}h ago — '{draft}'"
        )
    else:
        parts.append(f"on this topic ({topic_key}): no prior fires in {lookback_days}d")

    if any_topic and (not on_topic or any_topic.id != on_topic.id):
        delta = datetime.utcnow() - any_topic.event_at
        mins = int(delta.total_seconds() / 60)
        parts.append(
            f"most recent fire (any topic): {mins} min ago, "
            f"speech_act={any_topic.speech_act}, topic={any_topic.topic_key}"
        )
    elif not any_topic:
        parts.append(f"no proactive fires in {lookback_days}d at all")

    return "\n".join(parts)


async def load_user_state_now_block(*, user_id: str) -> str:
    """Render the USER STATE NOW block.

    Phase 2A keeps this lean — no Haiku tone read yet (that's Phase 2.5).
    Surfaces:
      - Time-of-day in user's tz (or UTC fallback)
      - Last user message (from chat_messages, if any in last 30 min)
      - Latest observation (from observations table, if any in last 36h)

    Real mood/focus inference lands later when the synthesis worker
    populates a richer state cache.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import ChatMessage, Observation, User
    except Exception:
        logger.exception("tier3 block: user_state imports failed")
        return f"{_PLACEHOLDER_PREFIX} user state unavailable"

    parts: list[str] = []

    try:
        async with async_session() as session:
            user_row = (
                await session.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one_or_none()
            tz_name = getattr(user_row, "timezone", None) or "UTC"

            try:
                from zoneinfo import ZoneInfo
                now_local = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now_local = datetime.utcnow()
            parts.append(f"local time: {now_local.strftime('%Y-%m-%d %H:%M %Z')}")

            # Last user message in last 30 min
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            last_user_msg = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.role == "user")
                    .where(ChatMessage.created_at >= cutoff)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if last_user_msg:
                content = (getattr(last_user_msg, "content", None) or "")[:80]
                age = datetime.utcnow() - last_user_msg.created_at
                mins = int(age.total_seconds() / 60)
                parts.append(f"last user msg: {mins}min ago — '{content}'")
            else:
                parts.append("no user messages in last 30 min")

            # Latest observation in last 36h
            obs_cutoff = datetime.utcnow() - timedelta(hours=36)
            last_obs = (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .where(Observation.event_time >= obs_cutoff)
                    .order_by(Observation.event_time.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_obs:
                kind = getattr(last_obs, "kind", None) or "obs"
                age = datetime.utcnow() - last_obs.event_time
                hours = int(age.total_seconds() / 3600)
                parts.append(f"last observation: {kind}, {hours}h ago")
            else:
                parts.append("no observations in last 36h")
    except Exception:
        logger.exception(
            "tier3 block: user_state query failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return f"{_PLACEHOLDER_PREFIX} user state query failed"

    return "\n".join(parts)
