from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select, update

from backend.db.models import ChatMessage, DonnaSchedule
from backend.db.session import async_session
from backend.memory.time import utcnow_naive
from delivery.whatsapp import WhatsAppChannel

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


async def run_once(*, batch_size: int = 25, lock_timeout_s: int = 60) -> int:
    """Send any due schedules. Returns number of schedules attempted."""
    now = utcnow_naive()
    wid = _worker_id()

    async with async_session() as session:
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
    wa = WhatsAppChannel()

    for row in rows:
        attempted += 1

        # Try to lock.
        async with async_session() as session:
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

            await wa.send_many(fresh.phone, constructed)

            chat_rows = fired_reminder_chat_rows(
                user_id=fresh.user_id, sent_messages=constructed
            )

            async with async_session() as session:
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
        except Exception as exc:
            logger.exception("schedule send failed id=%s", fresh.id)
            async with async_session() as session:
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

