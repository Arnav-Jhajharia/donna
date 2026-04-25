"""Bi-temporal facts repository tests.

Uses in-memory aiosqlite. JSONB columns fall back to JSON on SQLite, so
model binding still works for these tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


from backend.memory.facts import (
    get_as_of,
    get_current,
    list_history,
    record_fact,
    supersede_fact,
    update_fact,
)
from db.models import Base, User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        s.add(User(id="u1", phone="+1"))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_and_get_current(session: AsyncSession) -> None:
    f = await record_fact(
        session,
        user_id="u1",
        subject="user",
        predicate="lives_in",
        object="Mumbai",
    )
    assert f.t_valid_to is None
    assert f.t_recorded_to is None

    current = await get_current(
        session, user_id="u1", subject="user", predicate="lives_in"
    )
    assert current is not None
    assert current.object == "Mumbai"


@pytest.mark.asyncio
async def test_supersede_closes_old_and_links(session: AsyncSession) -> None:
    old = await record_fact(
        session, user_id="u1", subject="user", predicate="role", object="student"
    )
    new = await supersede_fact(
        session, old_id=old.id, new_object="engineer"
    )

    await session.refresh(old)
    assert old.t_recorded_to is not None
    assert old.superseded_by == new.id

    current = await get_current(
        session, user_id="u1", subject="user", predicate="role"
    )
    assert current is not None
    assert current.object == "engineer"


@pytest.mark.asyncio
async def test_update_preserves_past_belief(session: AsyncSession) -> None:
    """Real-world state change: student until Tuesday, engineer after."""
    monday = datetime(2026, 4, 20, 12, 0)
    tuesday = datetime(2026, 4, 21, 12, 0)

    f1 = await record_fact(
        session, user_id="u1", subject="user", predicate="role", object="student",
        t_valid_from=monday,
    )
    f1.t_recorded_from = monday
    await session.flush()

    await update_fact(session, old_id=f1.id, new_object="engineer", t_valid_from=tuesday)

    as_of_mon = await get_as_of(
        session, user_id="u1", subject="user", predicate="role", at_valid=monday,
    )
    assert as_of_mon is not None
    assert as_of_mon.object == "student"

    wed = datetime(2026, 4, 22, 12, 0)
    as_of_wed = await get_as_of(
        session, user_id="u1", subject="user", predicate="role", at_valid=wed,
    )
    assert as_of_wed is not None
    assert as_of_wed.object == "engineer"


@pytest.mark.asyncio
async def test_correction_retroactively_replaces_belief(session: AsyncSession) -> None:
    """Correction: we were wrong all along. Old belief is no longer held."""
    monday = datetime(2026, 4, 20, 12, 0)

    f1 = await record_fact(
        session, user_id="u1", subject="user", predicate="role", object="student",
        t_valid_from=monday,
    )
    f1.t_recorded_from = monday
    await session.flush()

    await supersede_fact(session, old_id=f1.id, new_object="engineer")

    # With today's knowledge, they were always an engineer.
    as_of_mon = await get_as_of(
        session, user_id="u1", subject="user", predicate="role", at_valid=monday,
    )
    assert as_of_mon is not None
    assert as_of_mon.object == "engineer"


@pytest.mark.asyncio
async def test_list_history_returns_all_rows(session: AsyncSession) -> None:
    f1 = await record_fact(
        session, user_id="u1", subject="user", predicate="mood", object="calm"
    )
    await supersede_fact(session, old_id=f1.id, new_object="anxious")
    history = await list_history(
        session, user_id="u1", subject="user", predicate="mood"
    )
    assert len(history) == 2
    assert history[0].object == "anxious"
    assert history[1].object == "calm"


@pytest.mark.asyncio
async def test_get_current_scoped_by_user(session: AsyncSession) -> None:
    session.add(User(id="u2", phone="+2"))
    await session.flush()

    await record_fact(
        session, user_id="u1", subject="user", predicate="city", object="Mumbai"
    )
    await record_fact(
        session, user_id="u2", subject="user", predicate="city", object="Tokyo"
    )

    c1 = await get_current(session, user_id="u1", subject="user", predicate="city")
    c2 = await get_current(session, user_id="u2", subject="user", predicate="city")
    assert c1 is not None and c1.object == "Mumbai"
    assert c2 is not None and c2.object == "Tokyo"
