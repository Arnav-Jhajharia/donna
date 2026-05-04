"""Unified proactive dispatcher.

Single funnel for every proactive trigger. Responsibilities:

  1. Consult the unified arbiter (quota / cooldown / quiet / topic / chat).
  2. Run Tier 2 judge.
  3. Apply the voice validator. Re-author once on uppercase / emoji.
  4. Ship draft / hold / drop / escalate based on the verdict.
  5. Record bookkeeping (ProactivePing rows, pending notes).

Phase 1 (mirror mode) only logs the verdict — no side effects beyond the
log line. Phase 2 (``DONNA_PROACTIVE_TIERED=1``) ships drafts, writes
ProactivePing rows, and inserts pending notes.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult, judge_event
from proactive.voice_validator import ValidationResult, validate

logger = logging.getLogger(__name__)


# Hold-lane TTL. Spec default: 12h. Per-source tunability deferred.
_PENDING_NOTE_TTL = timedelta(hours=12)
_TIERED_FLAG_ENV = "DONNA_PROACTIVE_TIERED"

DispatchAction = Literal[
    "mirror_logged",   # phase 1 only — no side effect
    "suppressed",      # arbiter denied (rate limit, quiet hours, etc.)
    "shipped",         # tier 2 ping shipped directly
    "held",            # tier 2 hold landed in pending_proactive_notes
    "dropped",         # tier 2 drop, suppressed_reason recorded
    "escalated",       # falling through to the brain
    "errored",         # internal failure, brain fallback path
]


@dataclass(frozen=True)
class DispatchOutcome:
    """Structured result of a dispatcher run.

    The dispatcher returns this regardless of mirror vs gated mode so the
    caller can pivot on the action and feed telemetry consistently.

    ``outbound`` is populated only by ``_escalate_to_brain`` so callers
    that need to ship the brain's buffer themselves (the schedule worker)
    can do so without re-invoking the brain. Empty / None means there is
    nothing for the caller to send.

    ``draft`` mirrors the validator-cleaned text the dispatcher actually
    used. Useful for the schedule worker writing its own ChatMessage row
    when ``action == 'held'`` (the held content is informational; no send
    happened, but the dashboard's recent chat block surfaces the queued
    note as a marker so the dashboard can distinguish 'held' from
    'shipped').
    """

    action: DispatchAction
    reason: str = ""
    judge: JudgeResult | None = None
    validator: ValidationResult | None = None
    note_id: str | None = None
    ping_id: str | None = None
    outbound: tuple[Any, ...] = ()
    draft: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_tiered_active() -> bool:
    """True when ``DONNA_PROACTIVE_TIERED`` is set to ``1``."""
    return os.getenv(_TIERED_FLAG_ENV, "0").strip() == "1"


def _session_factory():
    from backend.db.session import async_session

    return async_session


def _log_decision(
    event: ProactiveEvent,
    *,
    judge: JudgeResult | None,
    outcome: DispatchOutcome,
    validator: ValidationResult | None,
) -> None:
    """Structured log line ``proactive.tier2.decision`` for telemetry."""
    payload = {
        "event": "proactive.tier2.decision",
        "user_id": event.user_id,
        "source": event.source,
        "source_ref": event.source_ref,
        "topic_key": event.topic_key,
        "tiered_mode": is_tiered_active(),
        "outcome_action": outcome.action,
        "outcome_reason": outcome.reason,
    }
    if judge is not None:
        payload["judge_action"] = judge.action
        payload["judge_register"] = judge.register
        payload["judge_needs_tools"] = judge.needs_tools
        payload["judge_failed"] = judge.failed
        payload["judge_failure_reason"] = judge.failure_reason
        payload["judge_reasoning"] = (judge.reasoning or "")[:120]
    if validator is not None:
        payload["voice_reasons"] = list(validator.reasons)
        payload["voice_ok"] = validator.ok
    logger.info("proactive.tier2.decision %s", payload)


# -- Hold lane ---------------------------------------------------------------


async def insert_pending_note(
    event: ProactiveEvent, judge: JudgeResult
) -> str | None:
    """Insert a hold-lane row. Older rows on same topic_key marked superseded.

    Returns the new note id. None on insert failure (telemetry-logged
    upstream so the dispatcher can collapse to drop).
    """
    if not (judge.draft or "").strip():
        return None

    try:
        from sqlalchemy import update

        from db.models import PendingProactiveNote
    except Exception:
        logger.exception("dispatcher: PendingProactiveNote import failed")
        return None

    now = _utcnow()
    note_id = str(uuid.uuid4())
    try:
        async with _session_factory()() as session:
            if event.topic_key:
                await session.execute(
                    update(PendingProactiveNote)
                    .where(
                        PendingProactiveNote.user_id == event.user_id,
                        PendingProactiveNote.topic_key == event.topic_key,
                        PendingProactiveNote.status == "pending",
                    )
                    .values(status="superseded")
                )
            session.add(
                PendingProactiveNote(
                    id=note_id,
                    user_id=event.user_id,
                    source=event.source,
                    source_ref=event.source_ref,
                    topic_key=event.topic_key,
                    draft=judge.draft or "",
                    tie_in=list(judge.tie_in or ()),
                    reasoning=judge.reasoning or "",
                    status="pending",
                    created_at=now,
                    expires_at=now + _PENDING_NOTE_TTL,
                )
            )
            await session.commit()
        return note_id
    except Exception:
        logger.exception(
            "dispatcher: pending note insert failed user=%s topic=%s",
            event.user_id,
            event.topic_key,
        )
        return None


async def clear_pending_note(
    note_id: str,
    *,
    reason: str = "delivered",
) -> bool:
    """Mark a pending note delivered / irrelevant / superseded_by_user.

    Returns True when a row was updated. The brain calls this via the
    ``clear_pending_note`` tool when a burst it sends consumes the note.
    """
    valid_reasons = {"delivered", "irrelevant", "superseded_by_user"}
    if reason not in valid_reasons:
        reason = "delivered"
    try:
        from sqlalchemy import update

        from db.models import PendingProactiveNote
    except Exception:
        logger.exception("dispatcher: PendingProactiveNote import failed")
        return False

    now = _utcnow()
    try:
        async with _session_factory()() as session:
            result = await session.execute(
                update(PendingProactiveNote)
                .where(PendingProactiveNote.id == note_id)
                .where(PendingProactiveNote.status == "pending")
                .values(
                    status=reason,
                    delivered_at=now,
                )
            )
            await session.commit()
        return int(getattr(result, "rowcount", 0) or 0) > 0
    except Exception:
        logger.exception(
            "dispatcher: clear_pending_note failed id=%s",
            note_id,
        )
        return False


# -- Ship / escalate ---------------------------------------------------------


async def _user_phone(user_id: str) -> str | None:
    try:
        from sqlalchemy import select

        from db.models import User

        async with _session_factory()() as session:
            row = (
                await session.execute(
                    select(User.phone).where(User.id == user_id)
                )
            ).first()
        return row[0] if row else None
    except Exception:
        logger.exception(
            "dispatcher: user phone lookup failed user=%s", user_id
        )
        return None


async def _ship_draft(
    event: ProactiveEvent, judge: JudgeResult, draft: str
) -> DispatchOutcome:
    """Send the validated Tier 2 draft via WhatsApp + persist bookkeeping.

    Writes a ChatMessage(role='assistant', is_proactive=True), records a
    ProactivePing row keyed by topic, and dispatches a TextMessage burst.

    The schedule worker can avoid a redundant ``users`` lookup by stuffing
    ``phone`` into ``event.payload`` (we hold a phone on every
    ``DonnaSchedule`` row already). For sources without a payload phone we
    fall back to the users table.
    """
    payload_phone = (
        str(event.payload.get("phone") or "").strip()
        if isinstance(event.payload, dict)
        else ""
    )
    phone = payload_phone or await _user_phone(event.user_id)
    if not phone:
        return DispatchOutcome(
            action="errored",
            reason="user_phone_missing",
            judge=judge,
        )

    ping_id: str | None = None
    try:
        from delivery.messages import TextMessage
        from delivery.whatsapp import WhatsAppChannel

        channel = WhatsAppChannel()
        await channel.send_many(phone, [TextMessage(body=draft)])
    except Exception:
        logger.exception(
            "dispatcher: send failed user=%s topic=%s",
            event.user_id,
            event.topic_key,
        )
        return DispatchOutcome(
            action="errored",
            reason="send_failed",
            judge=judge,
        )

    try:
        from db.models import ChatMessage, ProactivePing

        ping_id = str(uuid.uuid4())
        now = _utcnow()
        async with _session_factory()() as session:
            chat_row = ChatMessage(
                user_id=event.user_id,
                role="assistant",
                content=draft,
                is_proactive=True,
                created_at=now,
            )
            session.add(chat_row)
            await session.flush()
            session.add(
                ProactivePing(
                    id=ping_id,
                    user_id=event.user_id,
                    source=event.source,
                    message_ref=event.source_ref,
                    topic_key=event.topic_key,
                    fired_at=now,
                )
            )
            await session.commit()
            try:
                from donna_runtime.observability import emit

                emit(
                    "proactive.delivered",
                    user_id=event.user_id,
                    source=event.source,
                    surface="dispatcher_tier2",
                    message_id=chat_row.id,
                    mode="live",
                    is_shadow=False,
                    topic_key=event.topic_key,
                    message_ref=event.source_ref,
                    ping_id=ping_id,
                    draft_preview=(draft or "")[:200],
                )
            except Exception:
                logger.exception(
                    "dispatcher: proactive.delivered emit failed user=%s",
                    event.user_id,
                )
    except Exception:
        logger.exception(
            "dispatcher: bookkeeping failed user=%s topic=%s",
            event.user_id,
            event.topic_key,
        )
        # The user already received the message; bookkeeping failure is
        # logged but the outcome remains "shipped" so the dispatcher's
        # caller does not double-fire.

    return DispatchOutcome(
        action="shipped",
        reason="tier2_ping",
        judge=judge,
        ping_id=ping_id,
        draft=draft,
    )


async def _escalate_to_brain(
    event: ProactiveEvent, judge: JudgeResult | None
) -> DispatchOutcome:
    """Fall through to the existing donna_turn proactive flow.

    Attaches the Tier 2 verdict (when present) on ``state["_tier2_proposal"]``
    so the brain prompt can use it as a hint.
    """
    try:
        from donna_runtime.brain import donna_turn
        from donna_runtime.config import DonnaAgentConfig
    except Exception:
        logger.exception(
            "dispatcher: brain imports failed user=%s", event.user_id
        )
        return DispatchOutcome(
            action="errored",
            reason="brain_import_failed",
            judge=judge,
        )

    # Pull phone for sources where the worker (not the brain channel)
    # ships the buffer. Email path's brain still goes via the SDK pipeline
    # which handles delivery; attention_fire callers need the buffer back.
    phone = event.payload.get("phone") if isinstance(event.payload, dict) else None
    if not phone:
        phone = await _user_phone(event.user_id)

    cfg = DonnaAgentConfig(
        mode="proactive",
        user_id=event.user_id,
        user_phone=phone,
        # See donna/attention/firing.py:fire_attention_via_brain — workers
        # have no filesystem access to the API container's SDK session
        # store, so proactive must always be stateless.
        stateless_sessions=True,
    )
    prompt = _build_escalation_prompt(event, judge)
    state: dict[str, Any] = {
        "user_id": event.user_id,
        "raw_input": prompt,
        "user_message": prompt,
        "phone": phone,
        "trigger": {
            "source": event.source,
            "message_ref": event.source_ref,
            "topic_key": event.topic_key,
            "score": event.signals.get("score"),
            "signals": event.signals.get("signals"),
        },
    }
    if judge is not None:
        state["_tier2_proposal"] = {
            "action": judge.action,
            "register": judge.register,
            "draft": judge.draft,
            "tie_in": list(judge.tie_in),
            "reasoning": judge.reasoning,
            "needs_tools": judge.needs_tools,
            "failed": judge.failed,
            "failure_reason": judge.failure_reason,
        }
    try:
        result = await donna_turn(state, cfg)
    except Exception:
        logger.exception(
            "dispatcher: donna_turn raised user=%s", event.user_id
        )
        return DispatchOutcome(
            action="errored",
            reason="brain_raised",
            judge=judge,
        )

    outbound: tuple[Any, ...] = ()
    if isinstance(result, dict):
        buf = result.get("_outbound") or []
        if isinstance(buf, list):
            outbound = tuple(buf)

    # Delivery semantics differ per source:
    #   - email: the historical legacy path leaves shipping to the brain's
    #     send_burst pipeline (today's behavior; we preserve it). The
    #     caller (proactive_email_trigger) does not double-ship either.
    #   - attention_fire / attention_offer: the schedule worker /
    #     promoter wants the buffer back so it can ship via WhatsApp the
    #     same way ``fire_attention_via_brain`` does today.
    # We hand back ``outbound`` in the outcome regardless; whether the
    # caller ships is the caller's call.

    # Bookkeep a non-suppressed ping so the global cooldown / quota tracks.
    try:
        from backend.integrations.proactive_rate_limit import record_ping

        await record_ping(
            event.user_id,
            event.source,
            event.source_ref,
            topic_key=event.topic_key,
        )
    except Exception:
        logger.exception(
            "dispatcher: record_ping after escalate failed user=%s",
            event.user_id,
        )

    # ──────────────────────────────────────────────────────────────────
    # PHASE 1 MIRROR: build the fat-contract Tier 3 input, log to telemetry.
    #
    # The Tier 3 brain itself is not invoked yet — that wiring lands in
    # Phase 2 once options.py picks the Tier 3 tool palette by cfg.mode.
    # Today we prove the input contract assembles + the dispatcher path
    # is wired + telemetry rows are written.
    # ──────────────────────────────────────────────────────────────────
    counterfactual_outcome: str | None = None
    counterfactual_elapsed_ms: int | None = None
    counterfactual_error: str | None = None
    started = time.monotonic()
    try:
        from donna_runtime.context_builder_tier3 import build_tier3_user_message

        # Phase 1: pre-built blocks are placeholder strings. Real block
        # builders (USER MODEL, DAY view, prior touches, etc.) land in
        # Phase 2 alongside the System B fold-in and cutover.
        _ = build_tier3_user_message(
            event=event,
            judge=judge if judge is not None else _placeholder_judge(),
            escalation_reason=(
                "needs_tools" if (judge and judge.needs_tools) else "tier2_failed"
            ),
            user_model_block="(phase 1 — USER MODEL block not yet populated)",
            queued_thing_block="(phase 1 — queued spec block not yet populated)",
            day_view_block="(phase 1 — DAY view block not yet populated)",
            prior_touches_block="(phase 1 — prior touches block not yet populated)",
            user_state_block="(phase 1 — user state block not yet populated)",
            pending_notes_block="(phase 1 — pending notes block not yet populated)",
            fresh_signal_block=None,
        )
        counterfactual_outcome = "input_built"
    except Exception as exc:  # noqa: BLE001 — best-effort, never block legacy
        logger.exception(
            "dispatcher: counterfactual input build raised user=%s",
            event.user_id,
        )
        counterfactual_outcome = "input_failed"
        counterfactual_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    counterfactual_elapsed_ms = int((time.monotonic() - started) * 1000)

    # Write telemetry. Best-effort — never block the legacy outcome.
    try:
        await _write_dispatch_telemetry(
            event=event,
            judge=judge,
            legacy_outbound_count=len(outbound),
            counterfactual_outcome=counterfactual_outcome,
            counterfactual_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_error=counterfactual_error,
        )
    except Exception:
        logger.exception(
            "dispatcher: telemetry write failed user=%s",
            event.user_id,
        )

    return DispatchOutcome(
        action="escalated",
        reason="needs_tools" if (judge and judge.needs_tools) else "fallback",
        judge=judge,
        outbound=outbound,
    )


def _placeholder_judge() -> "JudgeResult":
    """Construct a minimal placeholder JudgeResult for the counterfactual
    path when no Tier 2 verdict is available (e.g. Tier 2 timed out).
    Phase 1 mirror-mode safety net."""
    from proactive.judge import JudgeResult
    return JudgeResult(
        action="drop",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="(no tier 2 verdict — counterfactual placeholder)",
        raw_response="",
    )


async def _write_dispatch_telemetry(
    *,
    event: ProactiveEvent,
    judge: "JudgeResult | None",
    legacy_outbound_count: int,
    counterfactual_outcome: str | None,
    counterfactual_elapsed_ms: int | None,
    counterfactual_error: str | None,
) -> None:
    """Write one ProactiveDispatchTelemetry row. Best-effort.

    Phase 1: captures legacy outbound count + the counterfactual input-
    build outcome. The full Tier 3 turn (drafts, skip reasons) is not
    captured yet — that lands when the SDK tool wiring lands.
    """
    try:
        from backend.db.session import async_session
        from db.models import ProactiveDispatchTelemetry, generate_uuid
    except Exception:
        logger.exception("dispatcher: telemetry imports failed")
        return

    score: float | None = None
    if event.signals.get("score") is not None:
        try:
            score = float(event.signals["score"])
        except (TypeError, ValueError):
            score = None

    async with async_session() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id=event.user_id,
            source=event.source,
            speech_act=event.speech_act,
            topic_key=event.topic_key,
            tier1_score=score,
            arbiter_decision=None,
            arbiter_reason=None,
            tier2_action=judge.action if judge else None,
            tier2_register=judge.register if judge else None,
            tier2_draft=judge.draft if judge else None,
            tier2_needs_tools=judge.needs_tools if judge else None,
            tier2_channel_hint=getattr(judge, "channel_hint", None),
            tier2_reclassify=getattr(judge, "reclassify_speech_act", None),
            tier3_invoked=True,
            tier3_outcome="legacy_thin_directive",
            channel="whatsapp" if legacy_outbound_count > 0 else None,
            counterfactual_legacy_outbound_count=legacy_outbound_count,
            counterfactual_fat_contract_outcome=counterfactual_outcome,
            counterfactual_fat_contract_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_fat_contract_error=counterfactual_error,
        )
        session.add(row)
        await session.commit()


def _build_escalation_prompt(
    event: ProactiveEvent, judge: JudgeResult | None
) -> str:
    body_excerpt = str(event.payload.get("body_excerpt") or "")
    subject = str(event.payload.get("subject") or "")
    sender = str(
        event.payload.get("from_name")
        or event.payload.get("from_address")
        or ""
    )
    tier2_block = ""
    if judge is not None and not judge.failed:
        tie_in_str = ", ".join(judge.tie_in) if judge.tie_in else "none"
        tier2_block = (
            "\n\nTIER 2 PROPOSAL\n"
            f"action: {judge.action}\n"
            f"register: {judge.register or 'n/a'}\n"
            f"draft: {judge.draft or '(none)'}\n"
            f"tie_in: [{tie_in_str}]\n"
            f"reasoning: {judge.reasoning or '(none)'}\n"
            "ship the draft via send_burst as-is, or refine via your tools "
            "(recall, list_calendar, ...). the draft is a hint, not a "
            "constraint.\n"
        )
    elif judge is not None and judge.failed:
        tier2_block = (
            "\n\nTIER 2 STATUS: failed "
            f"({judge.failure_reason or 'unknown'}). "
            "no draft. decide from scratch.\n"
        )
    return (
        f"[SYSTEM TRIGGER: proactive_{event.source}]\n"
        "a proactive event arrived that may be worth surfacing. decide "
        "whether to ping the user. if it is not actually surface-worthy "
        "on a second look, SKIP THIS FIRE: do not call send_burst, just "
        "end the turn. NEVER substitute a generic check-in like 'what's "
        "on your mind', 'hey', 'anything brewing' — silence is correct "
        "when the event no longer warrants a ping.\n\n"
        f"from: {sender}\n"
        f"subject: {subject}\n"
        f"signals: {', '.join(event.signals.get('signals') or []) or 'none'}\n\n"
        f"{body_excerpt}"
        f"{tier2_block}"
    )


# -- Public dispatch ---------------------------------------------------------


async def dispatch(event: ProactiveEvent) -> DispatchOutcome:
    """Run the unified pipeline for one ``ProactiveEvent``.

    See module docstring for ordering. Mirror mode (``DONNA_PROACTIVE_TIERED``
    unset / 0) returns ``mirror_logged`` after Tier 2 — no DB writes, no
    sends. The legacy proactive path keeps running.
    """
    from backend.integrations.proactive_rate_limit import (
        can_fire_proactive,
        record_ping,
    )

    decision = await can_fire_proactive(
        event.user_id, source=event.source, topic_key=event.topic_key
    )
    if not decision.allowed:
        outcome = DispatchOutcome(
            action="suppressed",
            reason=decision.reason,
        )
        if is_tiered_active():
            try:
                await record_ping(
                    event.user_id,
                    event.source,
                    event.source_ref,
                    topic_key=event.topic_key,
                    suppressed_reason=decision.reason,
                )
            except Exception:
                logger.exception(
                    "dispatcher: record_ping suppress failed user=%s",
                    event.user_id,
                )
        _log_decision(event, judge=None, outcome=outcome, validator=None)
        return outcome

    judge = await judge_event(event)

    if judge.failed:
        outcome = DispatchOutcome(
            action="escalated" if is_tiered_active() else "mirror_logged",
            reason=f"tier2_failed:{judge.failure_reason}",
            judge=judge,
        )
        _log_decision(event, judge=judge, outcome=outcome, validator=None)
        if is_tiered_active():
            return await _escalate_to_brain(event, judge)
        return outcome

    if judge.action == "drop":
        outcome = DispatchOutcome(
            action="dropped",
            reason=f"tier2_drop:{(judge.reasoning or '')[:80]}",
            judge=judge,
        )
        if is_tiered_active():
            try:
                await record_ping(
                    event.user_id,
                    event.source,
                    event.source_ref,
                    topic_key=event.topic_key,
                    suppressed_reason=outcome.reason,
                )
            except Exception:
                logger.exception(
                    "dispatcher: record_ping drop failed user=%s",
                    event.user_id,
                )
        else:
            outcome = DispatchOutcome(
                action="mirror_logged",
                reason=outcome.reason,
                judge=judge,
            )
        _log_decision(event, judge=judge, outcome=outcome, validator=None)
        return outcome

    # ping or hold both produce drafts that must pass the voice net.
    validator = validate(judge.draft or "")
    if not validator.ok:
        # One re-author with explicit guidance, then escalate.
        re_judge = await _reauthor_once(event, judge, validator)
        if re_judge is not None:
            judge = re_judge
            validator = validate(judge.draft or "") if judge.draft else validator
        if judge.failed or not validator.ok:
            outcome = DispatchOutcome(
                action="escalated" if is_tiered_active() else "mirror_logged",
                reason="voice_violation",
                judge=judge,
                validator=validator,
            )
            _log_decision(event, judge=judge, outcome=outcome, validator=validator)
            if is_tiered_active():
                return await _escalate_to_brain(event, judge)
            return outcome

    final_draft = validator.cleaned

    if judge.action == "hold":
        if not is_tiered_active():
            outcome = DispatchOutcome(
                action="mirror_logged",
                reason="tier2_hold",
                judge=judge,
                validator=validator,
            )
            _log_decision(event, judge=judge, outcome=outcome, validator=validator)
            return outcome
        # Replace draft on the judge with the validator-cleaned text so
        # the persisted note matches what would have shipped.
        cleaned_judge = _replace_draft(judge, final_draft)
        note_id = await insert_pending_note(event, cleaned_judge)
        if note_id is None:
            outcome = DispatchOutcome(
                action="dropped",
                reason="hold_insert_failed",
                judge=cleaned_judge,
                validator=validator,
            )
            try:
                await record_ping(
                    event.user_id,
                    event.source,
                    event.source_ref,
                    topic_key=event.topic_key,
                    suppressed_reason="hold_insert_failed",
                )
            except Exception:
                logger.exception(
                    "dispatcher: record_ping hold-fail failed user=%s",
                    event.user_id,
                )
        else:
            outcome = DispatchOutcome(
                action="held",
                reason="tier2_hold",
                judge=cleaned_judge,
                validator=validator,
                note_id=note_id,
                draft=final_draft,
            )
        _log_decision(event, judge=cleaned_judge, outcome=outcome, validator=validator)
        return outcome

    # action == "ping"
    if judge.needs_tools:
        outcome = DispatchOutcome(
            action="escalated" if is_tiered_active() else "mirror_logged",
            reason="needs_tools",
            judge=judge,
            validator=validator,
        )
        _log_decision(event, judge=judge, outcome=outcome, validator=validator)
        if is_tiered_active():
            return await _escalate_to_brain(event, judge)
        return outcome

    if not is_tiered_active():
        outcome = DispatchOutcome(
            action="mirror_logged",
            reason="tier2_ping",
            judge=judge,
            validator=validator,
        )
        _log_decision(event, judge=judge, outcome=outcome, validator=validator)
        return outcome

    cleaned_judge = _replace_draft(judge, final_draft)
    outcome = await _ship_draft(event, cleaned_judge, final_draft)
    _log_decision(event, judge=cleaned_judge, outcome=outcome, validator=validator)
    return outcome


def _replace_draft(judge: JudgeResult, draft: str) -> JudgeResult:
    """Return a new JudgeResult with ``draft`` replaced. Frozen dataclass."""
    return JudgeResult(
        action=judge.action,
        register=judge.register,
        draft=draft,
        tie_in=judge.tie_in,
        needs_tools=judge.needs_tools,
        reasoning=judge.reasoning,
        raw_response=judge.raw_response,
        failed=judge.failed,
        failure_reason=judge.failure_reason,
        channel_hint=judge.channel_hint,
        reclassify_speech_act=judge.reclassify_speech_act,
    )


async def _reauthor_once(
    event: ProactiveEvent,
    judge: JudgeResult,
    validator: ValidationResult,
) -> JudgeResult | None:
    """Ask Tier 2 to retry with explicit voice guidance.

    Used when uppercase / emoji slipped past the prompt. Returns ``None``
    when the re-author path is unavailable (settings missing) so the
    dispatcher falls back to escalation.
    """
    # Only retry on uppercase / emoji — em-dash / semicolon are mechanical.
    retryable = {"uppercase_ratio", "emoji"}
    if not (set(validator.reasons) & retryable):
        return None

    instruction_bits = []
    if "uppercase_ratio" in validator.reasons:
        instruction_bits.append(
            "lowercase only. proper nouns like names and acronyms are fine, "
            "but no SHOUTING, no Title Case sentences."
        )
    if "emoji" in validator.reasons:
        instruction_bits.append("remove emojis. donna does not use emojis.")
    instruction = " ".join(instruction_bits)

    # We re-call judge_event with the same event but inject the
    # instruction by appending to the user message indirectly: the
    # cleanest plumbing is to call the underlying Haiku helper with a
    # tweaked system prompt. Keep it simple — append a fresh USER turn.
    try:
        from proactive.judge import (
            JUDGE_MODEL,
            JudgeOutput,
            _build_user_message,
            _gather_inputs,
            _load_prompt,
            _validate_output,
        )
    except Exception:
        logger.exception("dispatcher: re-author imports failed")
        return None

    system_prompt = (
        _load_prompt()
        + "\n\n## RETRY GUIDANCE\n"
        + instruction
        + "\nyour previous draft violated voice rules. emit a fresh JSON "
        + "object with a clean draft."
    )
    inputs = await _gather_inputs(event)
    user_message = (
        _build_user_message(inputs)
        + "\n\nyour earlier draft was: "
        + (judge.draft or "")
        + "\nit had voice issues: "
        + ", ".join(validator.reasons)
        + "\nemit a corrected JSON now."
    )

    try:
        from proactive.judge import _call_haiku

        parsed, raw = await _call_haiku(
            system_prompt=system_prompt,
            user_message=user_message,
        )
    except Exception:
        logger.exception("dispatcher: re-author call failed")
        return None

    if parsed is None:
        return JudgeResult(
            action=judge.action,
            register=judge.register,
            draft=judge.draft,
            tie_in=judge.tie_in,
            needs_tools=judge.needs_tools,
            reasoning=judge.reasoning,
            raw_response=judge.raw_response,
            failed=True,
            failure_reason=f"reauthor_failed:{raw[:80]}",
        )

    ok, failure = _validate_output(parsed)
    if not ok:
        return JudgeResult(
            action=judge.action,
            register=judge.register,
            draft=judge.draft,
            tie_in=judge.tie_in,
            needs_tools=judge.needs_tools,
            reasoning=judge.reasoning,
            raw_response=judge.raw_response,
            failed=True,
            failure_reason=f"reauthor_schema:{failure}",
        )

    return JudgeResult(
        action=parsed.action,
        register=parsed.register,
        draft=(parsed.draft or "").strip() or None,
        tie_in=tuple(parsed.tie_in or ()),
        needs_tools=bool(parsed.needs_tools),
        reasoning=(parsed.reasoning or "").strip(),
        raw_response=raw,
    )
