"""Tests for backend.web.proactive.store.

Uses the project's async session fixtures. The fixture must roll back
between tests; if your project uses a different fixture name adjust the
``async_db`` fixture import.
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

from backend.web.proactive.store import (
    DailyCountRepo,
    PostgresDedupStore,
    SignalQueueRepo,
)
from db.models import ProactiveSignal, ProactiveSubscription, User
from db.session import async_session


@pytest_asyncio.fixture
async def fresh_user() -> str:
    """Insert a throwaway user and return its id. Cleaned up by rollback fixture.

    Disposes the shared async engine before yielding so the asyncpg pool
    is bound to *this* test's event loop. Without this, pytest-asyncio's
    per-test loop scope conflicts with the module-level engine and causes
    "Event loop is closed" errors on the second-and-onward tests.
    """
    from datetime import datetime, timezone

    import db.session as _session_mod
    from db.models import ProactiveDailyCount, ProactiveLedger

    # Re-bind the engine to the current event loop. The module-level
    # engine was created at import time on a different loop.
    await _session_mod._engine.dispose()

    async def _wipe(session) -> None:
        # Defensive cleanup of any leftover rows from a prior run that
        # crashed before teardown (the fixture-cleanup path).
        await session.execute(
            ProactiveSignal.__table__.delete().where(
                ProactiveSignal.user_id == "u_test_proactive_store"
            )
        )
        await session.execute(
            ProactiveSubscription.__table__.delete().where(
                ProactiveSubscription.user_id == "u_test_proactive_store"
            )
        )
        await session.execute(
            ProactiveLedger.__table__.delete().where(
                ProactiveLedger.user_id == "u_test_proactive_store"
            )
        )
        await session.execute(
            ProactiveDailyCount.__table__.delete().where(
                ProactiveDailyCount.user_id == "u_test_proactive_store"
            )
        )
        await session.execute(
            User.__table__.delete().where(User.id == "u_test_proactive_store")
        )

    async with async_session() as session:
        await _wipe(session)
        u = User(
            id="u_test_proactive_store",
            phone="+19999999999",
            name="proactive store test",
            timezone="Asia/Singapore",
            living_profile={},
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(u)
        await session.commit()
    yield "u_test_proactive_store"
    async with async_session() as session:
        await _wipe(session)
        await session.commit()


@pytest.mark.asyncio
async def test_dedup_store_seen_returns_false_when_unseen(fresh_user):
    store = PostgresDedupStore(ttl_seconds=3600.0)
    assert await store.seen_async(fresh_user, "watch:foo", now=time.time()) is False


@pytest.mark.asyncio
async def test_dedup_store_mark_then_seen_is_true(fresh_user):
    store = PostgresDedupStore(ttl_seconds=3600.0)
    now = time.time()
    await store.mark_async(fresh_user, "watch:foo", now=now)
    assert await store.seen_async(fresh_user, "watch:foo", now=now) is True


@pytest.mark.asyncio
async def test_dedup_store_seen_expires_after_ttl(fresh_user):
    store = PostgresDedupStore(ttl_seconds=10.0)
    now = time.time()
    await store.mark_async(fresh_user, "watch:foo", now=now - 100.0)
    assert await store.seen_async(fresh_user, "watch:foo", now=now) is False


@pytest.mark.asyncio
async def test_daily_count_starts_at_zero(fresh_user):
    repo = DailyCountRepo()
    assert await repo.get(fresh_user, "2026-05-01") == 0


@pytest.mark.asyncio
async def test_daily_count_bump_increments(fresh_user):
    repo = DailyCountRepo()
    await repo.bump(fresh_user, "2026-05-01", by=1)
    await repo.bump(fresh_user, "2026-05-01", by=2)
    assert await repo.get(fresh_user, "2026-05-01") == 3


@pytest.mark.asyncio
async def test_signal_queue_enqueue_and_drain(fresh_user):
    # Need a subscription first
    from datetime import datetime, timezone
    async with async_session() as session:
        sub = ProactiveSubscription(
            id="sub_test_1",
            user_id=fresh_user,
            intent_key="watch:foo",
            description="watching foo",
            cadence="daily",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            last_refreshed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            active=True,
        )
        session.add(sub)
        await session.commit()

    queue = SignalQueueRepo()
    await queue.enqueue(
        user_id=fresh_user,
        subscription_id="sub_test_1",
        intent_key="watch:foo",
        payload={"title": "x", "url": "https://example.com/x"},
    )
    pending = await queue.drain_pending(fresh_user, limit=10)
    assert len(pending) == 1
    assert pending[0].payload["title"] == "x"

    # Mark consumed
    await queue.mark_consumed([pending[0].id])
    pending2 = await queue.drain_pending(fresh_user, limit=10)
    assert pending2 == []
