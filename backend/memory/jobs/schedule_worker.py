from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select, update

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
    return rows


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _lock_expired(locked_at: datetime | None, *, timeout_s: int) -> bool:
    if locked_at is None:
        return True
    # locked_at stored as naive UTC by convention
    return (utcnow_naive() - locked_at) > timedelta(seconds=timeout_s)


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


async def _fire_attention(row: DonnaSchedule) -> list:
    """Route an attention-linked fire through the dispatcher.

    Returns the outbound buffer the worker should ship via WhatsApp. An
    empty list means either:
      - the dispatcher already shipped (Tier 2 ping in gated mode), or
      - the dispatcher held / dropped / suppressed the event,
    in which case the worker must NOT send anything but should still
    mark the row ``fired=true``.

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
        return await fire_attention_via_brain(row)

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
        return await fire_attention_via_brain(row)

    action = outcome.action

    if action == "shipped":
        # Dispatcher already shipped + wrote ChatMessage + ProactivePing.
        return []

    if action == "held":
        # Pending-note row exists. Mirror the held draft into chat_messages
        # so the dashboard surfaces it as queued content.
        if outcome.draft:
            try:
                async with _session_factory()() as session:
                    session.add(
                        ChatMessage(
                            user_id=row.user_id,
                            role="assistant",
                            content=f"[held] {outcome.draft}",
                            is_proactive=True,
                        )
                    )
                    await session.commit()
            except Exception:
                logger.exception(
                    "schedule_worker: held chat-row insert failed "
                    "attention=%s",
                    row.attention_id,
                )
        return []

    if action in ("dropped", "suppressed"):
        return []

    if action == "escalated":
        # Brain decided. Outbound is the buffer the worker ships.
        return list(outcome.outbound or ())

    if action == "errored":
        # Brain wiring blew up inside the dispatcher. Fall back to the
        # legacy direct call so the user is not silently dropped.
        logger.warning(
            "schedule_worker: dispatcher errored=%s for attention=%s; "
            "falling back to legacy brain path",
            outcome.reason,
            row.attention_id,
        )
        return await fire_attention_via_brain(row)

    if action == "mirror_logged":
        # Defensive — should not happen with is_tiered_active=True.
        return await fire_attention_via_brain(row)

    # Unknown action. Be conservative — do nothing.
    logger.warning(
        "schedule_worker: unhandled dispatcher action=%s attention=%s",
        action,
        row.attention_id,
    )
    return []


async def run_once(*, batch_size: int = 25, lock_timeout_s: int = 60) -> int:
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
                constructed = await _fire_attention(fresh)
            else:
                payload = fresh.context or {}
                raw_items = payload.get("messages") if isinstance(payload, dict) else None
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


async def _maybe_enqueue_next_fire(row: DonnaSchedule) -> None:
    """For a fired attention-linked row with a recurring cadence, queue the next fire.

    No-op for one-shot reminders (legacy text reminders without ``attention_id``
    or PING attentions with ONE_SHOT cadence). Errors are logged, not raised —
    a missed re-enqueue must not break the just-completed delivery.
    """
    if not row.attention_id:
        return
    if not row.recurrence_meta:
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
    except Exception:
        logger.exception(
            "failed to enqueue next fire for attention=%s after schedule=%s",
            row.attention_id,
            row.id,
        )


async def run_forever(
    *,
    poll_interval_s: float = 5.0,
    batch_size: int = 25,
    lock_timeout_s: int = 60,
) -> None:
    while True:
        try:
            await run_once(batch_size=batch_size, lock_timeout_s=lock_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("schedule worker tick failed")
        await asyncio.sleep(poll_interval_s)

