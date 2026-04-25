"""Durable inbox helpers for WhatsApp inbound messages.

Thin DB layer over the InboundMessage model. The webhook handler inserts a
row per parsed message before dispatching; the pipeline marks rows processed
on success or failed on unrecoverable error. Cancelled pipelines leave rows
as 'queued' so the restart task re-processes them on the next dispatch.

On startup the replay helper returns every still-queued row so a crashed or
redeployed replica doesn't silently drop in-flight turns.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from db.models import InboundMessage
from db.session import async_session

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def insert_inbound(
    phone: str,
    wa_message_id: str | None,
    message: dict,
    value: dict,
) -> str | None:
    """Insert one queued inbox row. Returns row id, or None on failure.

    Stores the minimal {message, value} envelope so replay can rebuild an
    IngressPayload via ingress.whatsapp._parse_one without re-hitting Meta's
    dedup or retry machinery.
    """
    try:
        async with async_session() as session:
            row = InboundMessage(
                phone=phone,
                wa_message_id=wa_message_id,
                body={"message": message, "value": value},
                status="queued",
            )
            session.add(row)
            await session.commit()
            return row.id
    except Exception:
        logger.exception("inbound insert failed phone=%s wa_id=%s", phone[:6], wa_message_id)
        return None


async def mark_processed(row_ids: list[str]) -> None:
    if not row_ids:
        return
    try:
        async with async_session() as session:
            await session.execute(
                update(InboundMessage)
                .where(InboundMessage.id.in_(row_ids))
                .values(status="processed", processed_at=_utcnow())
            )
            await session.commit()
    except Exception:
        logger.exception("inbound mark_processed failed for %d rows", len(row_ids))


async def mark_failed(row_ids: list[str], error: str) -> None:
    if not row_ids:
        return
    try:
        truncated = (error or "")[:2000]
        async with async_session() as session:
            await session.execute(
                update(InboundMessage)
                .where(InboundMessage.id.in_(row_ids))
                .values(
                    status="failed",
                    error=truncated,
                    attempts=InboundMessage.attempts + 1,
                    processed_at=_utcnow(),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("inbound mark_failed failed for %d rows", len(row_ids))


async def fetch_queued_by_phone() -> dict[str, list[InboundMessage]]:
    """Return every still-queued row grouped by phone, oldest first per group.

    Used by startup replay. Callers should treat each phone's list as a
    chronological batch to merge through the normal dispatch path.
    """
    grouped: dict[str, list[InboundMessage]] = {}
    try:
        async with async_session() as session:
            result = await session.execute(
                select(InboundMessage)
                .where(InboundMessage.status == "queued")
                .order_by(InboundMessage.phone, InboundMessage.received_at)
            )
            for row in result.scalars().all():
                grouped.setdefault(row.phone, []).append(row)
    except Exception:
        logger.exception("inbound fetch_queued_by_phone failed")
    return grouped
