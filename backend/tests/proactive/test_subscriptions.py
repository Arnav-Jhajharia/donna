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


@pytest.mark.asyncio
async def test_provision_pending_websets_calls_exa_and_persists_ids(
    monkeypatch, user_with_watches
):
    """Pending subs (webset_id IS NULL) get provisioned via Exa client."""
    from backend.web.proactive import subscriptions as subs

    calls: list[tuple[str, dict]] = []

    async def fake_webset_create(query, **kw):
        calls.append(("webset", {"query": query, **kw}))
        return {"id": f"ws_{len(calls)}", "status": "pending"}

    async def fake_monitor_create(*, webset_id, cadence, behavior, **kw):
        calls.append(
            ("monitor", {"websetId": webset_id, "cadence": cadence, "behavior": behavior})
        )
        return {"id": f"mon_{webset_id}", "status": "active"}

    monkeypatch.setattr(subs, "exa_webset_create", fake_webset_create)
    monkeypatch.setattr(subs, "exa_monitor_create", fake_monitor_create)
    monkeypatch.setattr(subs, "have_exa_key", lambda: True)

    await subs.reconcile_subscriptions(user_with_watches)
    summary = await subs.provision_pending_websets(user_with_watches)
    assert summary.provisioned == 2
    assert summary.failed == 0
    # 2 websets + 2 monitors
    assert sum(1 for c in calls if c[0] == "webset") == 2
    assert sum(1 for c in calls if c[0] == "monitor") == 2

    # Re-running should be a no-op
    summary2 = await subs.provision_pending_websets(user_with_watches)
    assert summary2.provisioned == 0


@pytest.mark.asyncio
async def test_provision_pending_websets_no_op_without_exa_key(
    monkeypatch, user_with_watches
):
    from backend.web.proactive import subscriptions as subs

    monkeypatch.setattr(subs, "have_exa_key", lambda: False)
    await subs.reconcile_subscriptions(user_with_watches)
    summary = await subs.provision_pending_websets(user_with_watches)
    assert summary.provisioned == 0
    assert summary.failed == 0
