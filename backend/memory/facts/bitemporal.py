"""Bi-temporal facts repository — current belief, point-in-time, history.

All functions take an AsyncSession so callers control the transaction boundary.
Timestamps stored naive UTC to match the rest of the schema (see db.models.utcnow).

Semantics
---------
- record_fact: insert a new "current belief" row (both t_*_to are NULL).
- update_fact: the real-world state changed. Close the old row's t_valid_to
  at the new fact's t_valid_from. The old belief remains valid historically.
- supersede_fact: we were wrong. Close the old row's t_recorded_to and insert
  a replacement whose t_valid_from covers the same real-world window. Used
  for corrections, not state changes.
- get_current: current belief for (user, subject, predicate). None if none.
- get_as_of: what we believed was true, at real-world time `at_valid`, with
  knowledge we had by `at_recorded` (defaults to now).
- list_history: full ordered history for a (user, subject, predicate).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Fact, generate_uuid
from donna_runtime.observability import instrument_memory_op


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@instrument_memory_op("postgres.facts")
async def record_fact(
    session: AsyncSession,
    *,
    user_id: str,
    subject: str,
    predicate: str,
    object: str,
    object_json: dict[str, Any] | None = None,
    confidence: float = 1.0,
    source: str = "chat",
    t_valid_from: datetime | None = None,
) -> Fact:
    """Insert a new current-belief fact row.

    Does NOT close any existing belief. For corrections use supersede_fact.
    """
    now = _utcnow_naive()
    fact = Fact(
        id=generate_uuid(),
        user_id=user_id,
        subject=subject,
        predicate=predicate,
        object=object,
        object_json=object_json,
        confidence=confidence,
        source=source,
        t_valid_from=t_valid_from or now,
        t_valid_to=None,
        t_recorded_from=now,
        t_recorded_to=None,
        superseded_by=None,
    )
    session.add(fact)
    await session.flush()
    return fact


@instrument_memory_op("postgres.facts")
async def update_fact(
    session: AsyncSession,
    *,
    old_id: str,
    new_object: str,
    object_json: dict[str, Any] | None = None,
    confidence: float = 1.0,
    source: str = "chat",
    t_valid_from: datetime | None = None,
) -> Fact:
    """Real-world state changed. Close the old row's t_valid_to and insert.

    The old belief remains historically correct. Query "as of" a past time
    will still return the old row when that time falls inside its valid window.
    """
    now = _utcnow_naive()
    old = await session.get(Fact, old_id)
    if old is None:
        raise ValueError(f"fact {old_id!r} not found")

    cutover = t_valid_from or now
    new = Fact(
        id=generate_uuid(),
        user_id=old.user_id,
        subject=old.subject,
        predicate=old.predicate,
        object=new_object,
        object_json=object_json,
        confidence=confidence,
        source=source,
        t_valid_from=cutover,
        t_valid_to=None,
        t_recorded_from=now,
        t_recorded_to=None,
        superseded_by=None,
    )
    session.add(new)
    await session.flush()

    old.t_valid_to = cutover
    await session.flush()
    return new


@instrument_memory_op("postgres.facts")
async def supersede_fact(
    session: AsyncSession,
    *,
    old_id: str,
    new_object: str,
    object_json: dict[str, Any] | None = None,
    confidence: float = 1.0,
    source: str = "chat",
    t_valid_from: datetime | None = None,
) -> Fact:
    """We were wrong. Close the old row's t_recorded_to and insert a replacement.

    The new row's t_valid_from defaults to the old row's t_valid_from — the
    correction covers the same real-world window the wrong belief claimed.
    """
    now = _utcnow_naive()
    old = await session.get(Fact, old_id)
    if old is None:
        raise ValueError(f"fact {old_id!r} not found")

    new = Fact(
        id=generate_uuid(),
        user_id=old.user_id,
        subject=old.subject,
        predicate=old.predicate,
        object=new_object,
        object_json=object_json,
        confidence=confidence,
        source=source,
        t_valid_from=t_valid_from or old.t_valid_from,
        t_valid_to=None,
        t_recorded_from=now,
        t_recorded_to=None,
        superseded_by=None,
    )
    session.add(new)
    await session.flush()

    old.t_recorded_to = now
    old.superseded_by = new.id
    await session.flush()
    return new


@instrument_memory_op("postgres.facts")
async def get_current(
    session: AsyncSession,
    *,
    user_id: str,
    subject: str,
    predicate: str,
) -> Fact | None:
    """Return the current belief (open t_recorded_to, open t_valid_to)."""
    stmt = (
        select(Fact)
        .where(
            Fact.user_id == user_id,
            Fact.subject == subject,
            Fact.predicate == predicate,
            Fact.t_recorded_to.is_(None),
            Fact.t_valid_to.is_(None),
        )
        .order_by(Fact.t_recorded_from.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


@instrument_memory_op("postgres.facts")
async def get_as_of(
    session: AsyncSession,
    *,
    user_id: str,
    subject: str,
    predicate: str,
    at_valid: datetime,
    at_recorded: datetime | None = None,
) -> Fact | None:
    """Return what we believed at `at_recorded` was true at `at_valid`.

    at_recorded defaults to now. Both parameters must be naive UTC to match
    stored values.
    """
    at_recorded = at_recorded or _utcnow_naive()
    stmt = (
        select(Fact)
        .where(
            Fact.user_id == user_id,
            Fact.subject == subject,
            Fact.predicate == predicate,
            Fact.t_valid_from <= at_valid,
            or_(Fact.t_valid_to.is_(None), Fact.t_valid_to > at_valid),
            Fact.t_recorded_from <= at_recorded,
            or_(Fact.t_recorded_to.is_(None), Fact.t_recorded_to > at_recorded),
        )
        .order_by(Fact.t_recorded_from.desc(), Fact.t_valid_from.desc())
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


@instrument_memory_op("postgres.facts")
async def list_history(
    session: AsyncSession,
    *,
    user_id: str,
    subject: str,
    predicate: str,
    limit: int = 50,
) -> list[Fact]:
    """Return all fact rows for (user, subject, predicate), newest first."""
    stmt = (
        select(Fact)
        .where(
            Fact.user_id == user_id,
            Fact.subject == subject,
            Fact.predicate == predicate,
        )
        .order_by(Fact.t_recorded_from.desc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())
