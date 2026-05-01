"""Tests for triggers/drain.py."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.web.proactive.triggers.drain import maybe_drain_signals
from db.models import ProactiveSignal, ProactiveSubscription, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def user_with_signals() -> str:
    """Insert a throwaway user, subscription, and 3 pending signals.

    Re-binds the shared async engine to the current event loop, mirroring
    the workaround in ``test_store.py`` so per-test loops play nice with
    the module-level engine.
    """
    import db.session as _session_mod

    await _session_mod._engine.dispose()

    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_test_drain_{suffix}"
    sub_id = f"sub_drain_{suffix}"
    phone = f"+1999{suffix[:7]}"

    async with async_session() as session:
        u = User(
            id=user_id,
            phone=phone,
            name="drain test",
            timezone="UTC",
            living_profile={},
            created_at=_utcnow_naive(),
        )
        session.add(u)
        await session.commit()

    async with async_session() as session:
        sub = ProactiveSubscription(
            id=sub_id,
            user_id=user_id,
            intent_key="watch:drain_test",
            description="testing",
            cadence="daily",
            created_at=_utcnow_naive(),
            last_refreshed_at=_utcnow_naive(),
            active=True,
        )
        session.add(sub)
        await session.commit()

    async with async_session() as session:
        for i in range(3):
            session.add(
                ProactiveSignal(
                    user_id=user_id,
                    subscription_id=sub_id,
                    intent_key="watch:drain_test",
                    payload={
                        "title": f"item {i}",
                        "url": f"https://example.com/{i}",
                        "highlights": ["snippet"],
                    },
                )
            )
        await session.commit()
    yield user_id
    async with async_session() as session:
        await session.execute(
            ProactiveSignal.__table__.delete().where(
                ProactiveSignal.user_id == user_id
            )
        )
        await session.execute(
            ProactiveSubscription.__table__.delete().where(
                ProactiveSubscription.user_id == user_id
            )
        )
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_drain_marks_signals_consumed(monkeypatch, user_with_signals):
    """After drain runs, all signals are marked consumed regardless of
    judge verdict."""
    from backend.web.proactive.triggers import drain as d

    # Stub judge_results to silence everything (so we don't hit Anthropic
    # in tests). With no greenlit verdicts, deliver_drafts also does
    # nothing meaningful.
    from backend.web.proactive.judge import JudgeVerdict

    async def fake_judge(*, context, results):
        return [
            (r, JudgeVerdict(decision="silence", reason="test stub"))
            for r in results
        ]

    monkeypatch.setattr(d, "judge_results", fake_judge)

    decision = await maybe_drain_signals(
        user_id=user_with_signals,
        delivery_mode="shadow",
    )
    assert decision.signals_drained == 3
    # Re-running drains zero
    decision2 = await maybe_drain_signals(
        user_id=user_with_signals, delivery_mode="shadow"
    )
    assert decision2.signals_drained == 0
