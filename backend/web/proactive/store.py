"""Persistent stores for the proactive subsystem.

- ``PostgresDedupStore`` implements the async ``DedupStore`` Protocol
  from gates.py. Backed by ``proactive_ledger``.
- ``DailyCountRepo`` reads/writes ``proactive_daily_count`` rows. Used
  by the gates layer to enforce CostBudget.per_day across worker ticks.
- ``SignalQueueRepo`` enqueues Exa monitor hits and drains pending rows
  for the proactive runner.

All three are pure-async, return frozen DTOs, and never raise on missing
rows (they return safe empty values).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    ProactiveDailyCount,
    ProactiveLedger,
    ProactiveSignal,
)
from db.session import async_session


# ---------------------------------------------------------------------------
# dedup store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostgresDedupStore:
    """Async dedup ledger backed by ``proactive_ledger``.

    ``seen_async`` returns True when a row exists with ``fired_at`` newer
    than ``now - ttl_seconds``. The TTL is checked at read time, not by
    a sweeper — stale rows are tolerated. Run ``purge_older_than`` from
    a periodic job if the table grows.
    """

    # 24h TTL during the high-precision launch window. Same intent
    # firing twice in one day is almost always a sign the upstream
    # signal is the same news in a different wrapper. Bump back down
    # once judge calibration is settled.
    ttl_seconds: float = 24 * 3600.0

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool:
        cutoff = datetime.fromtimestamp(
            now - self.ttl_seconds, tz=timezone.utc
        ).replace(tzinfo=None)
        async with async_session() as session:
            row = (
                await session.execute(
                    select(ProactiveLedger.fired_at).where(
                        ProactiveLedger.user_id == user_id,
                        ProactiveLedger.dedup_key == dedup_key,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return False
        return row >= cutoff

    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None:
        when = datetime.fromtimestamp(now, tz=timezone.utc).replace(tzinfo=None)
        async with async_session() as session:
            stmt = (
                pg_insert(ProactiveLedger)
                .values(user_id=user_id, dedup_key=dedup_key, fired_at=when)
                .on_conflict_do_update(
                    index_elements=["user_id", "dedup_key"],
                    set_={"fired_at": when},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def purge_older_than(self, *, hours: int = 48) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=hours
        )
        async with async_session() as session:
            res = await session.execute(
                delete(ProactiveLedger).where(
                    ProactiveLedger.fired_at < cutoff
                )
            )
            await session.commit()
            return max(0, res.rowcount or 0)


# ---------------------------------------------------------------------------
# daily count repo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyCountRepo:
    """Per-user-per-local-day move counter."""

    async def get(self, user_id: str, local_date: str) -> int:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(ProactiveDailyCount.count).where(
                        ProactiveDailyCount.user_id == user_id,
                        ProactiveDailyCount.local_date == local_date,
                    )
                )
            ).scalar_one_or_none()
        return int(row or 0)

    async def bump(
        self, user_id: str, local_date: str, *, by: int = 1
    ) -> int:
        async with async_session() as session:
            stmt = (
                pg_insert(ProactiveDailyCount)
                .values(user_id=user_id, local_date=local_date, count=int(by))
                .on_conflict_do_update(
                    index_elements=["user_id", "local_date"],
                    set_={
                        "count": ProactiveDailyCount.count + int(by),
                    },
                )
                .returning(ProactiveDailyCount.count)
            )
            result = await session.execute(stmt)
            new_value = result.scalar_one()
            await session.commit()
            return int(new_value)


# ---------------------------------------------------------------------------
# signal queue repo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingSignal:
    """Read-only view of a pending proactive_signals row."""

    id: str
    subscription_id: str
    intent_key: str
    payload: dict[str, Any]
    arrived_at: datetime


@dataclass(frozen=True)
class SignalQueueRepo:
    """Enqueue Exa monitor hits and drain the pending queue per user."""

    async def enqueue(
        self,
        *,
        user_id: str,
        subscription_id: str,
        intent_key: str,
        payload: dict[str, Any],
    ) -> str:
        signal = ProactiveSignal(
            user_id=user_id,
            subscription_id=subscription_id,
            intent_key=intent_key,
            payload=dict(payload or {}),
        )
        async with async_session() as session:
            session.add(signal)
            await session.commit()
            return signal.id

    async def drain_pending(
        self, user_id: str, *, limit: int = 25
    ) -> list[PendingSignal]:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(ProactiveSignal)
                    .where(
                        ProactiveSignal.user_id == user_id,
                        ProactiveSignal.consumed_at.is_(None),
                    )
                    .order_by(ProactiveSignal.arrived_at.asc())
                    .limit(max(1, int(limit)))
                )
            ).scalars().all()
        return [
            PendingSignal(
                id=r.id,
                subscription_id=r.subscription_id,
                intent_key=r.intent_key,
                payload=dict(r.payload or {}),
                arrived_at=r.arrived_at,
            )
            for r in rows
        ]

    async def mark_consumed(self, signal_ids: list[str]) -> None:
        if not signal_ids:
            return
        when = datetime.now(timezone.utc).replace(tzinfo=None)
        async with async_session() as session:
            await session.execute(
                update(ProactiveSignal)
                .where(ProactiveSignal.id.in_(list(signal_ids)))
                .values(consumed_at=when)
            )
            await session.commit()
