from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import json

from sqlalchemy import cast, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB

import backend.db.session as _db_session_mod
from backend.db.models import ChatMessage, DonnaSchedule
from backend.memory.time import utcnow_naive


def _session_factory():
    """Lazy session-factory accessor.

    Returns the currently-bound `async_session` factory on the module.
    Tests monkeypatch ``backend.db.session.async_session`` after import,
    so resolving the attribute at call time honors the patch (vs. a
    top-level binding which captures the production factory).
    """
    return _db_session_mod.async_session
import delivery.whatsapp as _whatsapp_mod

logger = logging.getLogger(__name__)


def fired_reminder_chat_rows(
    *, user_id: str, sent_messages: Sequence[Any]
) -> list[ChatMessage]:
    """Build ChatMessage rows for a reminder that just fired.

    Mirrors how the BRAIN loop persists assistant turns: each renderable
    OutboundMessage becomes one assistant-role row, marked ``is_proactive``
    so the dashboard and context builder can distinguish reminder fires
    from in-loop replies. Delays, voice markers, and unrenderable items
    are skipped silently.
    """
    from donna_runtime.tool_logic import render_outbound_text

    rows: list[ChatMessage] = []
    for message in sent_messages:
        text = render_outbound_text(message)
        if not text:
            continue
        rows.append(
            ChatMessage(
                user_id=user_id,
                role="assistant",
                content=text,
                is_proactive=True,
            )
        )
    # Emit observability event per row so the trace dashboard can pick
    # these up. Done outside the persistence path so failures here never
    # block the worker.
    try:
        from donna_runtime.observability import emit

        for r in rows:
            emit(
                "proactive.delivered",
                user_id=user_id,
                source="schedule_worker",
                surface="schedule_worker/sent",
                mode="live",
                is_shadow=False,
                draft_preview=(r.content or "")[:200],
            )
    except Exception:
        logger.exception(
            "schedule_worker: proactive.delivered emit failed user=%s",
            user_id,
        )
    return rows


def _build_fallback_outbound(context: dict | None) -> list:
    """Build OutboundMessages from a schedule row's ``context.messages``.

    Used as the deterministic floor when the brain returns empty outbound
    for a user-requested fire — see Fix 9 in the plan. Returns an empty
    list when context lacks a renderable ``messages`` array. Callers
    decide what to do with the empty case (intentional skip vs alert).
    """
    payload = context or {}
    raw_items = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        return []
    from donna_runtime.tool_logic import _build_outbound

    out: list = []
    for item in raw_items:
        msg = _build_outbound(item)
        if msg is not None:
            out.append(msg)
    return out


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _lock_expired(locked_at: datetime | None, *, timeout_s: int) -> bool:
    if locked_at is None:
        return True
    # locked_at stored as naive UTC by convention
    return (utcnow_naive() - locked_at) > timedelta(seconds=timeout_s)


async def _maybe_render_feature_cron(row: DonnaSchedule) -> str | None:
    """Call the registered feature cron handler to compose a body.

    Returns the handler's string output, or ``None`` when:
      - ``recurrence_meta.handler`` is missing or unregistered
      - the feature row is gone (archived between schedule + fire)
      - the handler itself returns ``None`` (intentional silence,
        e.g. evening_summary on a clean-miss day)
      - any exception bubbles (logged + swallowed)

    The caller treats ``None`` as "skip silently" and the legacy
    literal-"reminder" fallback never runs for a row that opted into
    a feature handler.
    """
    meta = row.recurrence_meta or {}
    handler_name = meta.get("handler") if isinstance(meta, dict) else None
    if not handler_name:
        return None
    try:
        from backend.db.models import Feature
        from backend.features.handlers import (
            get_cron_handler,
            is_cron_handler_registered,
        )
    except Exception:
        return None
    if not is_cron_handler_registered(handler_name):
        logger.warning(
            "schedule_worker: feature cron handler %r not registered "
            "(feature_id=%s schedule_id=%s)",
            handler_name,
            row.feature_id,
            row.id,
        )
        return None
    handler = get_cron_handler(handler_name)
    try:
        async with _session_factory()() as session:
            feature = (
                await session.execute(
                    select(Feature).where(Feature.id == row.feature_id)
                )
            ).scalar_one_or_none()
            if feature is None or feature.status != "active":
                return None
            return await handler(
                session=session,
                user_id=row.user_id,
                feature=feature,
                schedule_row=row,
            )
    except Exception:
        logger.exception(
            "schedule_worker: feature cron handler %r raised "
            "(feature_id=%s schedule_id=%s)",
            handler_name,
            row.feature_id,
            row.id,
        )
        return None


async def _hydrate_attention(attention_id: str | None):
    """Best-effort fetch the linked Attention. Returns None on any miss.

    The attention store is file-backed today and may be unreachable in
    production environments where the worker runs separately. Swallow
    errors so the dispatcher still gets the schedule row.
    """
    if not attention_id:
        return None
    try:
        from donna.attention.store import AttentionStore

        return AttentionStore().get(attention_id)
    except Exception:
        logger.exception(
            "schedule_worker: attention hydrate failed id=%s", attention_id
        )
        return None


async def _fire_attention(row: DonnaSchedule) -> tuple[list, bool]:
    """Route an attention-linked fire through the dispatcher.

    Returns ``(outbound, already_shipped)``:
      - ``outbound`` is the buffer the worker should ship via WhatsApp
        (empty for shipped/held/dropped paths)
      - ``already_shipped`` is True when the dispatcher itself sent the
        message (Tier 2 ship path); the caller must NOT double-send and
        must NOT fire any deterministic-body fallback.

    Mirror mode (``DONNA_PROACTIVE_TIERED`` unset / 0) collapses to the
    legacy ``fire_attention_via_brain`` path so existing behavior is
    preserved bit-for-bit.

    Held drafts are written to ``chat_messages`` as
    ``is_proactive=True`` rows so the dashboard's recent chat reflects
    queued content. A ``[held]`` marker prefixes the body so the UI can
    distinguish held from shipped without a schema change. The pending
    note row in ``pending_proactive_notes`` is the canonical store; the
    chat row is informational.
    """
    from donna.attention.firing import fire_attention_via_brain
    from proactive.dispatcher import dispatch as dispatcher_dispatch
    from proactive.dispatcher import is_tiered_active
    from proactive.sources.attention_fire import make_event

    if not is_tiered_active():
        # Mirror mode — preserve today's path unchanged.
        return await fire_attention_via_brain(row), False

    attention = await _hydrate_attention(row.attention_id)
    event = make_event(row, attention)
    # Stash phone on the payload so the dispatcher's ship path skips a
    # redundant users-table lookup. Schedule rows always carry phone.
    if row.phone:
        event = event.__class__(
            user_id=event.user_id,
            source=event.source,
            source_ref=event.source_ref,
            topic_key=event.topic_key,
            payload={**event.payload, "phone": row.phone},
            signals=event.signals,
        )

    try:
        outcome = await dispatcher_dispatch(event)
    except Exception:
        logger.exception(
            "schedule_worker: dispatcher raised attention=%s; "
            "falling back to legacy brain path",
            row.attention_id,
        )
        return await fire_attention_via_brain(row), False

    action = outcome.action

    if action == "shipped":
        # Dispatcher already shipped + wrote ChatMessage + ProactivePing.
        return [], True

    if action == "held":
        # Pending-note row exists. Mirror the held draft into chat_messages
        # so the dashboard surfaces it as queued content.
        if outcome.draft:
            try:
                async with _session_factory()() as session:
                    held = ChatMessage(
                        user_id=row.user_id,
                        role="assistant",
                        content=f"[held] {outcome.draft}",
                        is_proactive=True,
                    )
                    session.add(held)
                    await session.flush()
                    await session.commit()
                try:
                    from donna_runtime.observability import emit

                    emit(
                        "proactive.delivered",
                        user_id=row.user_id,
                        source="schedule_worker_held",
                        surface="schedule_worker/held",
                        message_id=held.id,
                        mode="held",
                        is_shadow=True,
                        attention_id=row.attention_id,
                        schedule_id=row.id,
                        draft_preview=(outcome.draft or "")[:200],
                    )
                except Exception:
                    logger.exception(
                        "schedule_worker: held emit failed attention=%s",
                        row.attention_id,
                    )
            except Exception:
                logger.exception(
                    "schedule_worker: held chat-row insert failed "
                    "attention=%s",
                    row.attention_id,
                )
        # Held: dispatcher wrote a ``[held]`` chat row but did NOT send
        # WhatsApp. Treat this as already-handled — the fallback path
        # would double up on user-visible content.
        return [], True

    if action in ("dropped", "suppressed"):
        # Dispatcher decided to skip. No send, no fallback.
        return [], True

    if action == "escalated":
        # Brain decided. Outbound is the buffer the worker ships.
        return list(outcome.outbound or ()), False

    if action == "errored":
        # Brain wiring blew up inside the dispatcher. Fall back to the
        # legacy direct call so the user is not silently dropped.
        logger.warning(
            "schedule_worker: dispatcher errored=%s for attention=%s; "
            "falling back to legacy brain path",
            outcome.reason,
            row.attention_id,
        )
        return await fire_attention_via_brain(row), False

    if action == "mirror_logged":
        # Defensive — should not happen with is_tiered_active=True.
        return await fire_attention_via_brain(row), False

    # Unknown action. Be conservative — do nothing.
    logger.warning(
        "schedule_worker: unhandled dispatcher action=%s attention=%s",
        action,
        row.attention_id,
    )
    return [], False


async def run_once(*, batch_size: int = 25, lock_timeout_s: int = 300) -> int:
    """Send any due schedules. Returns number of schedules attempted."""
    now = utcnow_naive()
    wid = _worker_id()

    async with _session_factory()() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.fired.is_(False))
                .where(DonnaSchedule.status.in_(("pending", "running")))
                .where(DonnaSchedule.fire_at <= now)
                .order_by(DonnaSchedule.fire_at.asc())
                .limit(batch_size)
            )
        ).scalars().all()

    if not rows:
        return 0

    attempted = 0
    # Resolve via the module so test monkeypatch of
    # ``delivery.whatsapp.WhatsAppChannel`` is honored at call time.
    wa = _whatsapp_mod.WhatsAppChannel()

    for row in rows:
        attempted += 1

        # Try to lock.
        async with _session_factory()() as session:
            fresh = (
                await session.execute(
                    select(DonnaSchedule).where(DonnaSchedule.id == row.id)
                )
            ).scalar_one_or_none()
            if fresh is None:
                continue
            if fresh.fired:
                continue
            if not _lock_expired(fresh.locked_at, timeout_s=lock_timeout_s) and fresh.locked_by and fresh.locked_by != wid:
                continue

            await session.execute(
                update(DonnaSchedule)
                .where(DonnaSchedule.id == fresh.id)
                .values(status="running", locked_at=now, locked_by=wid)
            )
            await session.commit()

        try:
            if fresh.attention_id:
                # Attention-linked fire: route through the unified Tier 2
                # dispatcher when ``DONNA_PROACTIVE_TIERED=1``. In mirror
                # mode (default) the dispatcher returns ``mirror_logged``
                # and we fall back to the legacy ``fire_attention_via_brain``
                # path so behavior is bit-for-bit identical to today.
                constructed, already_shipped = await _fire_attention(fresh)

                # Floor-level reliability: if the brain returned empty
                # outbound for a USER-requested fire (origin='user'), fall
                # back to the deterministic context body. Silent drops on
                # explicit user requests are the worst failure mode —
                # CLAUDE.md: "a reminder that doesn't fire is not a bug,
                # it's a betrayal." Brain composition is the upgrade path;
                # the deterministic body is the floor. Donna-initiated
                # proactive fires (origin='donna') with empty outbound are
                # intentional skips by the dispatcher / brain — we trust
                # that decision and stay silent. ``already_shipped=True``
                # means the dispatcher itself sent the message (Tier 2
                # ship path); we must NOT double-send a fallback.
                if (
                    not constructed
                    and not already_shipped
                    and (fresh.origin or "").lower() == "user"
                ):
                    constructed = _build_fallback_outbound(fresh.context)
                    if constructed:
                        logger.warning(
                            "schedule_worker: brain empty for user-requested fire "
                            "id=%s attention=%s, falling back to context body",
                            fresh.id,
                            fresh.attention_id,
                        )
                        try:
                            from donna_runtime.observability import emit

                            emit(
                                "proactive.fallback_fired",
                                user_id=fresh.user_id,
                                source="schedule_worker",
                                surface="schedule_worker/fallback",
                                attention_id=fresh.attention_id,
                                schedule_id=str(fresh.id),
                            )
                        except Exception:
                            logger.exception(
                                "schedule_worker: fallback_fired emit failed"
                            )

                # If still empty AND the dispatcher didn't itself ship,
                # distinguish intentional skip (origin=donna) from silent-
                # drop class (origin=user with no context body — alert).
                # When ``already_shipped`` is True the dispatcher already
                # delivered to WhatsApp so there is nothing to skip.
                if not constructed and not already_shipped:
                    skip_kind = (
                        "alert_silent_drop"
                        if (fresh.origin or "").lower() == "user"
                        else "intentional_skip"
                    )
                    try:
                        from donna_runtime.observability import emit

                        emit(
                            "proactive.skipped_silent",
                            user_id=fresh.user_id,
                            source="schedule_worker",
                            surface="schedule_worker/empty",
                            attention_id=fresh.attention_id,
                            schedule_id=str(fresh.id),
                            origin=fresh.origin,
                            kind=skip_kind,
                        )
                    except Exception:
                        logger.exception(
                            "schedule_worker: skipped_silent emit failed"
                        )
                    if skip_kind == "alert_silent_drop":
                        logger.error(
                            "schedule_worker: SILENT DROP id=%s attention=%s "
                            "user=%s origin=%s — user-requested fire "
                            "produced no outbound and no fallback content. "
                            "This is a reliability alert.",
                            fresh.id,
                            fresh.attention_id,
                            fresh.user_id,
                            fresh.origin,
                        )
            else:
                payload = fresh.context or {}
                raw_items = payload.get("messages") if isinstance(payload, dict) else None

                # Feature cron path — if the row carries a registered
                # feature handler, call it to compose the body. Falls
                # through to the legacy ``context.messages`` path below
                # when no handler is registered.
                if raw_items is None and fresh.feature_id and fresh.recurrence_meta:
                    handler_body = await _maybe_render_feature_cron(fresh)
                    if handler_body is None:
                        # Handler chose silence — mark the row done with a
                        # breadcrumb instead of firing the literal-"reminder"
                        # fallback.
                        async with _session_factory()() as session:
                            await session.execute(
                                update(DonnaSchedule)
                                .where(DonnaSchedule.id == fresh.id)
                                .values(
                                    fired=True,
                                    fired_at=utcnow_naive(),
                                    status="done",
                                    last_error="feature_handler_silent",
                                    locked_at=None,
                                    locked_by=None,
                                )
                            )
                            await session.commit()
                        await _maybe_enqueue_next_fire(fresh)
                        continue
                    raw_items = [{"type": "text", "body": handler_body}]

                items = raw_items if isinstance(raw_items, list) else [{"type": "text", "body": "reminder"}]

                from donna_runtime.tool_logic import _build_outbound

                constructed = []
                for item in items:
                    msg = _build_outbound(item)
                    if msg is not None:
                        constructed.append(msg)
                if not constructed:
                    constructed = [_build_outbound({"type": "text", "body": "reminder"})]
                    constructed = [m for m in constructed if m is not None]

            if constructed:
                await wa.send_many(fresh.phone, constructed)

            chat_rows = fired_reminder_chat_rows(
                user_id=fresh.user_id, sent_messages=constructed
            )

            async with _session_factory()() as session:
                for chat_row in chat_rows:
                    session.add(chat_row)
                await session.execute(
                    update(DonnaSchedule)
                    .where(DonnaSchedule.id == fresh.id)
                    .values(
                        fired=True,
                        fired_at=utcnow_naive(),
                        status="done",
                        last_error=None,
                        attempts=DonnaSchedule.attempts + 1,
                        locked_at=None,
                        locked_by=None,
                    )
                )
                await session.commit()

            await _maybe_record_attention_surface(fresh)
            await _maybe_enqueue_next_fire(fresh)
            await _maybe_resolve_completed_attention(fresh)
            await _append_day_fire(fresh, constructed)
        except Exception as exc:
            logger.exception("schedule send failed id=%s", fresh.id)
            async with _session_factory()() as session:
                await session.execute(
                    update(DonnaSchedule)
                    .where(DonnaSchedule.id == fresh.id)
                    .values(
                        status="pending",
                        last_error=f"{type(exc).__name__}: {str(exc)[:500]}",
                        attempts=DonnaSchedule.attempts + 1,
                        locked_at=None,
                        locked_by=None,
                    )
                )
                await session.commit()

    return attempted


async def _append_day_fire(row: DonnaSchedule, outbound: list) -> None:
    """Append a schedule fire record to today's user_days.schedule_fires.

    Best-effort — a failure here never blocks delivery.
    """
    if not row.user_id or not row.fired_at:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert
        from zoneinfo import ZoneInfo

        from db.models import UserDay, generate_uuid, utcnow

        ctx = row.context or {}
        msgs = ctx.get("messages") or []
        title = (
            (msgs[0].get("body") or "")[:60]
            if msgs
            else ctx.get("title") or row.attention_id or "reminder"
        )

        # Capture what was actually sent, not just the attention trigger name.
        sent_preview = ""
        if outbound:
            try:
                from donna_runtime.tool_logic import render_outbound_text

                parts = [render_outbound_text(m) for m in outbound]
                sent_preview = " ".join(p for p in parts if p)[:300]
            except Exception:
                pass

        try:
            tz = ZoneInfo(ctx.get("timezone") or "Asia/Singapore")
        except Exception:
            tz = ZoneInfo("Asia/Singapore")

        fired_local = row.fired_at.replace(tzinfo=None)
        try:
            from datetime import timezone as _tz
            fired_local = row.fired_at.replace(tzinfo=_tz.utc).astimezone(tz)
        except Exception:
            pass

        fire_record = {
            "title": title,
            "sent": sent_preview,
            "fired_at_local": fired_local.strftime("%H:%M") if hasattr(fired_local, "strftime") else str(row.fired_at)[:16],
            "attention_id": row.attention_id or "",
        }
        date_local = fired_local.strftime("%Y-%m-%d") if hasattr(fired_local, "strftime") else ""
        if not date_local:
            return

        now = utcnow()
        async with _session_factory()() as session:
            # INSERT or UPDATE. On conflict, append to the JSONB array with ||
            # (atomic at the Postgres level — no read-modify-write race).
            fire_literal = cast(literal(json.dumps([fire_record])), JSONB)
            await session.execute(
                insert(UserDay)
                .values(
                    id=generate_uuid(),
                    user_id=row.user_id,
                    date_local=date_local,
                    timezone=ctx.get("timezone") or "Asia/Singapore",
                    schedule_fires=[fire_record],
                    donna_message_count=len(outbound),
                    donna_proactive_count=1,
                    observation_types=[],
                    finalized=False,
                    updated_at=now,
                    created_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_user_days_user_date",
                    set_={
                        "schedule_fires": UserDay.schedule_fires.op("||")(fire_literal),
                        "donna_message_count": UserDay.donna_message_count + len(outbound),
                        "donna_proactive_count": UserDay.donna_proactive_count + 1,
                        "updated_at": now,
                    },
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "schedule_worker: _append_day_fire failed schedule=%s", row.id
        )


async def _maybe_record_attention_surface(row: DonnaSchedule) -> None:
    """Stamp ``attentions.last_surfaced_at`` after a successful delivery.

    Best-effort. A failure here must not roll back the just-completed
    send (already committed by the caller). No-op for legacy rows that
    have no ``attention_id``.
    """
    if not row.attention_id:
        return
    try:
        from donna.attention.postgres_store import record_last_surfaced
    except Exception:
        logger.exception(
            "attention postgres_store unavailable; cannot stamp last_surfaced_at"
        )
        return
    try:
        await record_last_surfaced(row.attention_id, at=row.fired_at)
    except Exception:
        logger.exception(
            "failed to record last_surfaced_at for attention=%s schedule=%s",
            row.attention_id,
            row.id,
        )


async def _maybe_resolve_completed_attention(row: DonnaSchedule) -> None:
    """For an attention-linked one-shot fire, mark the attention RESOLVED.

    Recurring attentions stay LIVE (their next fire is queued by
    ``_maybe_enqueue_next_fire``). One-shot attentions otherwise live forever
    in the LIVE list and pollute every reactive turn's TODAY block.

    Best-effort: errors are logged, not raised. The fire already shipped.
    """
    if not row.attention_id:
        return
    if not row.recurrence_meta:
        return
    try:
        from donna.attention.firing import RecurrenceMeta
    except Exception:
        return
    meta = RecurrenceMeta.from_jsonb(row.recurrence_meta)
    if meta is None or meta.is_recurring:
        return
    try:
        from donna.attention.postgres_store import update_attention_status
        from donna.attention.schema import AttentionStatus

        await update_attention_status(row.attention_id, AttentionStatus.RESOLVED)
    except Exception:
        logger.exception(
            "failed to resolve completed one-shot attention=%s schedule=%s",
            row.attention_id,
            row.id,
        )
    try:
        from donna.attention.tools import resolve_attention as _file_resolve

        _file_resolve(row.attention_id)
    except Exception:
        logger.info(
            "file-store resolve skipped for attention=%s (best-effort)",
            row.attention_id,
        )


_ENGAGEMENT_BACKOFF_LIMIT = 3  # consecutive non-replies before pausing
_ENGAGEMENT_BACKOFF_LOOKBACK = 12  # how many recent fires to inspect


async def _consecutive_non_replies(
    user_id: str, attention_id: str
) -> int:
    """Count how many of the most recent fires for this attention got no
    user reply between the fire and the next event. The reply heuristic
    is "any user-side ChatMessage strictly after the fire_at".

    Returns 0 if the most recent fire WAS replied to (resets the streak),
    or N if the last N consecutive fires got no reply.
    """
    from sqlalchemy import desc
    from db.models import ChatMessage
    from backend.db.session import async_session as _session_factory

    try:
        async with _session_factory() as session:
            recent_fires = (
                await session.execute(
                    select(DonnaSchedule.fire_at)
                    .where(
                        DonnaSchedule.user_id == user_id,
                        DonnaSchedule.attention_id == attention_id,
                        DonnaSchedule.fired.is_(True),
                    )
                    .order_by(desc(DonnaSchedule.fire_at))
                    .limit(_ENGAGEMENT_BACKOFF_LOOKBACK)
                )
            ).all()
            fires = [r[0] for r in recent_fires if r[0] is not None]
            if not fires:
                return 0
            # Walk most-recent-first; count consecutive fires until we see
            # a user-side reply that landed after the fire.
            streak = 0
            for fire_at in fires:
                reply_count = (
                    await session.execute(
                        select(ChatMessage.id)
                        .where(
                            ChatMessage.user_id == user_id,
                            ChatMessage.role == "user",
                            ChatMessage.created_at > fire_at,
                            ChatMessage.is_shadow.is_(False),
                        )
                        .limit(1)
                    )
                ).first()
                if reply_count:
                    return streak
                streak += 1
            return streak
    except Exception:
        logger.exception(
            "engagement backoff: failed to count non-replies user=%s attn=%s",
            user_id[:8] if user_id else "?",
            attention_id[:8] if attention_id else "?",
        )
        return 0


async def _maybe_enqueue_next_fire(row: DonnaSchedule) -> None:
    """For a fired row with a recurring cadence, queue the next fire.

    Handles two shapes:
      - Attention-linked rows (``row.attention_id`` set): subject to the
        engagement backoff (skip recurrence after N consecutive non-replies).
      - Unattached reminders (``row.attention_id`` is None): created via
        the simple ``remind`` tool. No engagement backoff — the user
        explicitly opted in to the cadence and can ``cancel_reminder``.

    No-op for one-shot fires (no recurrence_meta or non-recurring cadence).
    Errors are logged, not raised — a missed re-enqueue must not break
    the just-completed delivery.
    """
    if not row.recurrence_meta:
        return

    if row.attention_id:
        streak = await _consecutive_non_replies(row.user_id, row.attention_id)
        if streak >= _ENGAGEMENT_BACKOFF_LIMIT:
            logger.info(
                "engagement backoff: pausing attn=%s user=%s after %d consecutive non-replies",
                row.attention_id[:8],
                row.user_id[:8],
                streak,
            )
            return

    try:
        from donna.attention.firing import RecurrenceMeta, compute_next_fire
    except Exception:
        logger.exception("attention firing module unavailable; skipping re-enqueue")
        return

    meta = RecurrenceMeta.from_jsonb(row.recurrence_meta)
    if meta is None or not meta.is_recurring:
        return

    cadence = meta.to_cadence()
    next_fire = compute_next_fire(
        cadence,
        after=row.fire_at if row.fire_at is not None else utcnow_naive(),
        tz=meta.user_tz or "UTC",
    )
    if next_fire is None:
        return

    fire_at_naive = next_fire.replace(tzinfo=None)
    # Lazy import so test monkeypatching of backend.db.session.async_session
    # is picked up. Module-level imports bind at load time and miss the
    # patch.
    from backend.db.session import async_session as _session_factory

    # Retry the enqueue on transient DB blips. A single failure here used to
    # kill recurring reminders forever — the user delivery already succeeded
    # so there's no upstream retry. 3 attempts with backoff catches the
    # 99% case (connection reset, lock contention) without unbounded delay.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with _session_factory() as session:
                session.add(
                    DonnaSchedule(
                        user_id=row.user_id,
                        phone=row.phone,
                        fire_at=fire_at_naive,
                        origin=row.origin,
                        recurrence=row.recurrence,
                        context=dict(row.context or {}),
                        attention_id=row.attention_id,
                        recurrence_meta=dict(row.recurrence_meta),
                        fired=False,
                        status="pending",
                    )
                )
                await session.commit()
            return
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
    # All retries exhausted. Emit a high-signal event so the recurring
    # reminder isn't silently dropped — operators must know to re-enqueue
    # by hand or the user loses this attention's recurrence.
    try:
        from donna_runtime.observability import emit

        emit(
            "proactive.recurrence_enqueue_failed",
            user_id=row.user_id,
            attention_id=row.attention_id,
            schedule_id=row.id,
            next_fire_at=fire_at_naive.isoformat() if fire_at_naive else None,
            error=f"{type(last_exc).__name__}: {str(last_exc)[:300]}" if last_exc else "unknown",
        )
    except Exception:
        pass
    logger.error(
        "RECURRENCE LOST: failed to enqueue next fire for attention=%s after schedule=%s next_fire=%s err=%s",
        row.attention_id,
        row.id,
        fire_at_naive,
        type(last_exc).__name__ if last_exc else "unknown",
    )


async def _check_missed_fires(*, threshold_s: int = 60) -> int:
    """Detect DonnaSchedule rows that should have fired but didn't.

    A row is "missed" when ``fire_at + threshold_s`` is in the past, the
    row is not yet ``fired``, and its status is one we'd otherwise expect
    the worker to drain (``pending`` or ``running``). ``cancelled`` /
    ``paused`` / ``done`` are excluded.

    Per CLAUDE.md non-negotiable: "A DonnaSchedule row that hasn't fired
    by fire_at + 60s is an alert." This is that alert. Each missed row
    emits a structured ``proactive.missed_fire`` event AND an ERROR-level
    log line so it surfaces in any aggregator without further plumbing.

    Returns the number of missed rows detected this cycle. Does NOT modify
    the rows — the worker's normal lock/retry path still owns them, this
    is purely a visibility hook so silent failures stop being silent.
    """
    cutoff = utcnow_naive() - timedelta(seconds=threshold_s)
    try:
        async with _session_factory()() as session:
            rows = (
                await session.execute(
                    select(DonnaSchedule)
                    .where(DonnaSchedule.fired.is_(False))
                    .where(DonnaSchedule.fire_at < cutoff)
                    .where(DonnaSchedule.status.in_(("pending", "running")))
                    .order_by(DonnaSchedule.fire_at.asc())
                    .limit(100)
                )
            ).scalars().all()
    except Exception:
        logger.exception("missed-fire check: query failed")
        return 0

    if not rows:
        return 0

    try:
        from donna_runtime.observability import emit
    except Exception:
        emit = None  # type: ignore[assignment]

    now = utcnow_naive()
    for row in rows:
        overdue_s = int((now - row.fire_at).total_seconds()) if row.fire_at else None
        if emit is not None:
            try:
                emit(
                    "proactive.missed_fire",
                    schedule_id=row.id,
                    user_id=row.user_id,
                    attention_id=row.attention_id,
                    fire_at=row.fire_at.isoformat() if row.fire_at else None,
                    overdue_seconds=overdue_s,
                    status=row.status,
                    attempts=row.attempts,
                    last_error=row.last_error,
                    locked_by=row.locked_by,
                )
            except Exception:
                pass
        logger.error(
            "MISSED FIRE: schedule=%s user=%s attn=%s overdue=%ss status=%s attempts=%s last_err=%s",
            row.id,
            (row.user_id or "")[:8],
            (row.attention_id or "")[:8] if row.attention_id else "—",
            overdue_s,
            row.status,
            row.attempts,
            (row.last_error or "")[:120] if row.last_error else None,
        )
    return len(rows)


async def run_forever(
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 25,
    lock_timeout_s: int = 300,
    missed_fire_threshold_s: int = 60,
) -> None:
    while True:
        try:
            await run_once(batch_size=batch_size, lock_timeout_s=lock_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("schedule worker tick failed")
        try:
            await _check_missed_fires(threshold_s=missed_fire_threshold_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("missed-fire check failed")
        await asyncio.sleep(poll_interval_s)

