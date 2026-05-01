"""Phase 1 smoke: insert a synthetic move, gate-accept it, mark fired,
verify it gets dedup-rejected on the next pass within TTL.
"""
from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio

from backend.web.proactive.gates import CostBudget, apply_gates
from backend.web.proactive.store import PostgresDedupStore
from backend.web.proactive.types import ProactiveMove
from db.models import ProactiveLedger, User
from db.session import async_session


@pytest_asyncio.fixture
async def fresh_user() -> str:
    """Insert a throwaway user and return its id. Cleaned up at fixture exit.

    Disposes the shared async engine before yielding so the asyncpg pool
    is bound to *this* test's event loop. Without this, pytest-asyncio's
    per-test loop scope conflicts with the module-level engine and causes
    "Event loop is closed" errors.
    """
    from datetime import datetime, timezone

    import db.session as _session_mod

    # Re-bind the engine to the current event loop.
    await _session_mod._engine.dispose()

    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_test_phase1_smoke_{suffix}"
    phone = f"+1999{suffix[:7]}"

    async with async_session() as session:
        u = User(
            id=user_id,
            phone=phone,
            name="phase1 smoke",
            timezone="UTC",
            living_profile={},
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(u)
        await session.commit()
    yield user_id
    # Clean up ledger rows first (FK to users) then the user itself.
    async with async_session() as session:
        await session.execute(
            ProactiveLedger.__table__.delete().where(
                ProactiveLedger.user_id == user_id
            )
        )
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_round_trip_dedup(fresh_user):
    move = ProactiveMove(
        rationale="testing dedup",
        tool="search",
        query="hello world test query",
        dedup_key="watch:test_phase1",
    )
    ledger = PostgresDedupStore(ttl_seconds=3600.0)

    outcome1 = await apply_gates(
        [move],
        user_id=fresh_user,
        ledger=ledger,
        budget=CostBudget(per_turn=3, per_day=10),
        daily_used=0,
    )
    assert len(outcome1.accepted) == 1

    # Mark the dedup key as fired.
    await ledger.mark_async(fresh_user, move.dedup_key, now=time.time())

    outcome2 = await apply_gates(
        [move],
        user_id=fresh_user,
        ledger=ledger,
        budget=CostBudget(per_turn=3, per_day=10),
        daily_used=0,
    )
    assert outcome2.accepted == []
    assert any("dedup" in d.reason for d in outcome2.dropped)
