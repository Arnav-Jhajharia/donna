"""Postgres-backed store for Attention objects.

Companion to :mod:`donna.attention.store` (file-JSON). Production paths
dual-write to both — postgres is the durable cross-process source of
truth, the file store keeps tests / cli / proactive jobs offline-friendly.

API is intentionally async to match the rest of the postgres-backed code
(``backend.db.session.async_session``). All helpers import the session
factory lazily inside the function body so test monkey-patching works.

Read paths (``get_attention``, ``list_attentions_by_user``) materialize
back into the in-memory ``donna.attention.schema.Attention`` so the rest
of the system never has to know about the ORM row shape.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from donna.attention.schema import Attention, AttentionStatus

logger = logging.getLogger(__name__)


# -- Write paths ------------------------------------------------------------


async def persist_attention(attention: Attention, *, user_id: str) -> None:
    """Upsert an attention into postgres.

    ``user_id`` is passed in (rather than read from ``attention.user_id``)
    because the pydantic model coerces handles to UUIDs while the FK to
    ``users.id`` expects exact string equality.
    """
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.db.session import async_session

    payload = attention.model_dump(mode="json")
    title = attention.spec.title
    card = attention.spec.card.value
    cadence_type = attention.spec.cadence.type.value
    origin = attention.origin.value
    status = attention.status.value
    last_surfaced_at = _naive_utc(attention.last_surfaced_at)
    created_at = _naive_utc(attention.created_at) or _now_naive_utc()

    async with async_session() as session:
        existing = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                AttentionRow(
                    id=str(attention.id),
                    user_id=user_id,
                    title=title,
                    card=card,
                    cadence_type=cadence_type,
                    origin=origin,
                    status=status,
                    payload=payload,
                    last_surfaced_at=last_surfaced_at,
                    created_at=created_at,
                )
            )
        else:
            existing.title = title
            existing.card = card
            existing.cadence_type = cadence_type
            existing.origin = origin
            existing.status = status
            existing.payload = payload
            existing.last_surfaced_at = last_surfaced_at
        await session.commit()


async def update_attention_status(
    attention_id: str, status: AttentionStatus
) -> bool:
    """Flip ``status`` and bump ``updated_at`` + the JSONB mirror.

    Returns True if a row was updated, False if the attention is unknown
    (e.g. created via the file store and never dual-written). Callers
    that already wrote-through during ``persist_attention`` can ignore
    the False return; it is not an error.
    """
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == attention_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.status = status.value
        # Keep the JSONB payload's status field in sync so a reader that
        # round-trips ``payload`` back into the pydantic model sees the
        # current state.
        if isinstance(row.payload, dict):
            row.payload = {**row.payload, "status": status.value}
        await session.commit()
        return True


async def record_last_surfaced(
    attention_id: str, *, at: datetime | None = None
) -> bool:
    """Stamp ``last_surfaced_at`` after a successful fire."""
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.db.session import async_session

    stamp = _naive_utc(at) or _now_naive_utc()
    async with async_session() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == attention_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.last_surfaced_at = stamp
        if isinstance(row.payload, dict):
            row.payload = {
                **row.payload,
                "last_surfaced_at": stamp.replace(tzinfo=timezone.utc).isoformat(),
                "update_count": int(row.payload.get("update_count", 0)) + 1,
            }
        await session.commit()
        return True


# -- Read paths -------------------------------------------------------------


async def get_attention(attention_id: str) -> Attention | None:
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == attention_id)
            )
        ).scalar_one_or_none()
    return _row_to_attention(row)


async def list_attentions_by_user(
    user_id: str, *, status: AttentionStatus | None = None
) -> list[Attention]:
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.db.session import async_session

    async with async_session() as session:
        stmt = select(AttentionRow).where(AttentionRow.user_id == user_id)
        if status is not None:
            stmt = stmt.where(AttentionRow.status == status.value)
        stmt = stmt.order_by(AttentionRow.created_at.desc())
        rows = (await session.execute(stmt)).scalars().all()
    out: list[Attention] = []
    for r in rows:
        att = _row_to_attention(r)
        if att is not None:
            out.append(att)
    return out


# -- Internals --------------------------------------------------------------


def _row_to_attention(row: Any) -> Attention | None:
    if row is None:
        return None
    if not isinstance(row.payload, dict):
        return None
    try:
        return Attention.model_validate(row.payload)
    except Exception:
        logger.exception("attentions.id=%s payload failed validation", row.id)
        return None


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -- UUID coercion helper (re-exported for parity with file store API) -----


def coerce_user_id_for_fk(value: str | UUID) -> str:
    """Identity helper kept so callers don't need to know the FK is plain str."""
    return str(value)
