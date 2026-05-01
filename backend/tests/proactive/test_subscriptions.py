"""Tests for subscriptions.reconcile_subscriptions.

The function reads ``users.living_profile.watch_for_tomorrow``, diffs
against active rows in ``proactive_subscriptions`` for that user, and:
- creates a new ``ProactiveSubscription`` row for any watch line not
  already represented (with webset_id/monitor_id None — actual Exa
  calls happen in a separate function under test in Task 7).
- deactivates rows whose intent_key no longer appears in watch_for_tomorrow.
- enforces the per-user budget: oldest active subs LRU-evicted when over.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.web.proactive.subscriptions import (
    intent_key_for_watch_line,
    reconcile_subscriptions,
)
from db.models import ProactiveSubscription, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def user_with_watches() -> str:
    """Insert a throwaway user with watch_for_tomorrow set; clean up after."""
    import db.session as _session_mod

    # Re-bind the engine to the current event loop. The module-level engine
    # was created at import time on a different loop.
    await _session_mod._engine.dispose()

    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_test_recon_{suffix}"
    phone = f"+1999{suffix[:7]}"

    async with async_session() as session:
        u = User(
            id=user_id,
            phone=phone,
            name="recon test",
            timezone="UTC",
            living_profile={
                "watch_for_tomorrow": [
                    "antler sg batch 13 announcements",
                    "openai sora pricing changes",
                ],
            },
            created_at=_utcnow_naive(),
        )
        session.add(u)
        await session.commit()
    yield user_id
    async with async_session() as session:
        await session.execute(
            ProactiveSubscription.__table__.delete().where(
                ProactiveSubscription.user_id == user_id
            )
        )
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


def test_intent_key_for_watch_line_is_stable_and_lowercase():
    a = intent_key_for_watch_line("Antler SG batch 13")
    b = intent_key_for_watch_line("antler sg batch 13")
    assert a == b
    assert a.startswith("watch:")
    assert " " not in a


@pytest.mark.asyncio
async def test_reconcile_creates_rows_for_new_watches(user_with_watches):
    summary = await reconcile_subscriptions(user_with_watches)
    assert summary.created == 2
    assert summary.deactivated == 0

    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.user_id == user_with_watches,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).scalars().all()
    assert len(rows) == 2
    keys = {r.intent_key for r in rows}
    assert any("antler" in k for k in keys)
    assert any("sora" in k for k in keys)


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(user_with_watches):
    s1 = await reconcile_subscriptions(user_with_watches)
    s2 = await reconcile_subscriptions(user_with_watches)
    assert s1.created == 2
    assert s2.created == 0


@pytest.mark.asyncio
async def test_reconcile_deactivates_dropped_watches(user_with_watches):
    await reconcile_subscriptions(user_with_watches)

    # Drop one watch
    async with async_session() as session:
        u = (
            await session.execute(
                select(User).where(User.id == user_with_watches)
            )
        ).scalar_one()
        u.living_profile = {
            "watch_for_tomorrow": ["antler sg batch 13 announcements"],
        }
        await session.commit()

    summary = await reconcile_subscriptions(user_with_watches)
    assert summary.deactivated == 1


@pytest.mark.asyncio
async def test_reconcile_enforces_budget_lru(user_with_watches):
    """When watch list exceeds budget, oldest non-listed are evicted."""
    # Reduce budget to 1 for the test
    summary = await reconcile_subscriptions(user_with_watches, max_active=1)
    assert summary.created == 1
    assert summary.skipped_over_budget == 1
