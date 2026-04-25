"""Timezone writes should mirror into the bitemporal facts table.

Covers the four cases from the plan:
  (a) first set → record_fact row exists
  (b) same tz again → no new row, no update_fact
  (c) different tz → update_fact closes old, history has 2 rows
  (d) get_as_of(at_valid=past) returns the old belief

Uses in-memory aiosqlite + the same JSONB→JSON compile fallback as
test_bitemporal_facts.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


from backend.memory.facts import get_as_of, get_current, list_history
from backend.memory.tools.set_timezone import record_timezone_fact
from db.models import Base, User


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure user row exists. record_timezone_fact uses async_session under
    # the hood, so we also monkey async_session to point at our engine.
    maker = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        s.add(User(id="u1", phone="+1"))
        await s.commit()

    yield eng, maker
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _patch_session(engine, monkeypatch):
    _eng, maker = engine
    from backend.db import session as session_mod

    monkeypatch.setattr(session_mod, "async_session", maker)


@pytest.mark.asyncio
async def test_first_set_records_fact(engine):
    _eng, maker = engine
    fact_id = await record_timezone_fact("u1", "Asia/Singapore")
    assert fact_id is not None

    async with maker() as s:
        current = await get_current(
            s, user_id="u1", subject="user", predicate="current_timezone"
        )
    assert current is not None
    assert current.object == "Asia/Singapore"


@pytest.mark.asyncio
async def test_same_tz_is_no_op(engine):
    _eng, maker = engine
    first = await record_timezone_fact("u1", "Asia/Singapore")
    repeat = await record_timezone_fact("u1", "Asia/Singapore")

    assert first is not None
    assert repeat is None, "re-writing the same tz should not insert a new row"

    async with maker() as s:
        history = await list_history(
            s, user_id="u1", subject="user", predicate="current_timezone"
        )
    assert len(history) == 1


@pytest.mark.asyncio
async def test_different_tz_updates_and_preserves_history(engine):
    _eng, maker = engine
    await record_timezone_fact("u1", "Asia/Singapore")
    new_id = await record_timezone_fact("u1", "America/New_York")
    assert new_id is not None

    async with maker() as s:
        history = await list_history(
            s, user_id="u1", subject="user", predicate="current_timezone"
        )
        current = await get_current(
            s, user_id="u1", subject="user", predicate="current_timezone"
        )

    assert current is not None
    assert current.object == "America/New_York"
    assert len(history) == 2

    # The older row should have t_valid_to closed out.
    older = next(f for f in history if f.object == "Asia/Singapore")
    assert older.t_valid_to is not None


@pytest.mark.asyncio
async def test_get_as_of_returns_old_belief(engine):
    """What we believed yesterday should still be retrievable via at_valid."""
    _eng, maker = engine
    monday = datetime(2026, 4, 20, 12, 0)
    tuesday = datetime(2026, 4, 21, 12, 0)

    # Seed the first row directly so we control t_valid_from.
    from backend.memory.facts import record_fact, update_fact
    async with maker() as s:
        old = await record_fact(
            s,
            user_id="u1",
            subject="user",
            predicate="current_timezone",
            object="Asia/Singapore",
            source="user_correction",
            t_valid_from=monday,
        )
        old.t_recorded_from = monday
        await s.commit()

        await update_fact(
            s,
            old_id=old.id,
            new_object="America/New_York",
            source="user_correction",
            t_valid_from=tuesday,
        )
        await s.commit()

    async with maker() as s:
        at_mon = await get_as_of(
            s,
            user_id="u1",
            subject="user",
            predicate="current_timezone",
            at_valid=monday,
        )
        at_wed = await get_as_of(
            s,
            user_id="u1",
            subject="user",
            predicate="current_timezone",
            at_valid=datetime(2026, 4, 22, 12, 0),
        )

    assert at_mon is not None and at_mon.object == "Asia/Singapore"
    assert at_wed is not None and at_wed.object == "America/New_York"


@pytest.mark.asyncio
async def test_home_timezone_uses_distinct_predicate(engine):
    """home_timezone and current_timezone are orthogonal."""
    _eng, maker = engine
    await record_timezone_fact("u1", "Asia/Kolkata", predicate="home_timezone")
    await record_timezone_fact("u1", "America/New_York", predicate="current_timezone")

    async with maker() as s:
        home = await get_current(
            s, user_id="u1", subject="user", predicate="home_timezone"
        )
        current = await get_current(
            s, user_id="u1", subject="user", predicate="current_timezone"
        )

    assert home is not None and home.object == "Asia/Kolkata"
    assert current is not None and current.object == "America/New_York"
