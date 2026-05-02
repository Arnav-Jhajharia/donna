"""Tests for the missed-fire detector and recurrence-retry safety net.

Both behaviours added to schedule_worker because silent failures violate
the brand promise that "Donna holds your life." A missed schedule fire
must alert; a transient DB blip during recurrence enqueue must retry,
not lose the recurrence forever.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@pytest_asyncio.fixture
async def db(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from db.models import Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session() as s:
        s.add(User(id="u1", phone="+15551234567", timezone="Asia/Singapore"))
        await s.commit()

    import backend.db.session as backend_session
    import db.session as root_session

    monkeypatch.setattr(root_session, "async_session", test_session)
    monkeypatch.setattr(backend_session, "async_session", test_session)

    try:
        yield test_session
    finally:
        await engine.dispose()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_missed_fire_detected_when_past_threshold(db, caplog) -> None:
    """A pending row whose fire_at is older than threshold should alert."""
    import logging

    from db.models import DonnaSchedule

    from backend.memory.jobs.schedule_worker import _check_missed_fires

    now = _utcnow_naive()
    async with db() as s:
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now - timedelta(seconds=300),
            origin="user",
            context={"messages": [{"type": "text", "body": "test"}]},
            fired=False,
            status="pending",
        ))
        await s.commit()

    with caplog.at_level(logging.ERROR, logger="backend.memory.jobs.schedule_worker"):
        n = await _check_missed_fires(threshold_s=60)

    assert n == 1
    assert any("MISSED FIRE" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_missed_fire_ignores_already_fired(db) -> None:
    """A row that already fired must not raise an alert even if old."""
    from db.models import DonnaSchedule

    from backend.memory.jobs.schedule_worker import _check_missed_fires

    now = _utcnow_naive()
    async with db() as s:
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now - timedelta(seconds=600),
            fired_at=now - timedelta(seconds=580),
            origin="user",
            fired=True,
            status="done",
        ))
        await s.commit()

    n = await _check_missed_fires(threshold_s=60)
    assert n == 0


@pytest.mark.asyncio
async def test_missed_fire_ignores_cancelled_and_paused(db) -> None:
    """Cancelled and paused rows are intentional, not alerts."""
    from db.models import DonnaSchedule

    from backend.memory.jobs.schedule_worker import _check_missed_fires

    now = _utcnow_naive()
    async with db() as s:
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now - timedelta(seconds=600),
            origin="user",
            fired=False,
            status="cancelled",
        ))
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now - timedelta(seconds=600),
            origin="user",
            fired=False,
            status="paused",
        ))
        await s.commit()

    n = await _check_missed_fires(threshold_s=60)
    assert n == 0


@pytest.mark.asyncio
async def test_missed_fire_ignores_future_rows(db) -> None:
    """Rows whose fire_at is still in the future are not missed."""
    from db.models import DonnaSchedule

    from backend.memory.jobs.schedule_worker import _check_missed_fires

    now = _utcnow_naive()
    async with db() as s:
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now + timedelta(seconds=300),
            origin="user",
            fired=False,
            status="pending",
        ))
        await s.commit()

    n = await _check_missed_fires(threshold_s=60)
    assert n == 0


@pytest.mark.asyncio
async def test_missed_fire_within_threshold_is_silent(db) -> None:
    """A row 30s late with a 60s threshold is not yet alertable."""
    from db.models import DonnaSchedule

    from backend.memory.jobs.schedule_worker import _check_missed_fires

    now = _utcnow_naive()
    async with db() as s:
        s.add(DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=now - timedelta(seconds=30),
            origin="user",
            fired=False,
            status="pending",
        ))
        await s.commit()

    n = await _check_missed_fires(threshold_s=60)
    assert n == 0
