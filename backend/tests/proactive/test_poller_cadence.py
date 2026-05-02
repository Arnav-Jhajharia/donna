"""Tests for the cadence-aware poller.

Under the /search-only model, the poller calls ``exa_search`` for each
subscription whose cadence interval has elapsed since ``last_hit_at``.
Subs whose interval hasn't elapsed are silently skipped — that's how
we honor the deriver's daily/weekly/monthly cadence choice without
paying credits to over-poll.

Each ``/search`` costs ~5 credits at Exa, so the cadence gate is the
single biggest knob protecting our budget.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.web.proactive import poller as poller_mod
from backend.web.proactive.poller import (
    _CADENCE_TO_INTERVAL,
    _is_due,
    poll_pending_subscriptions,
)
from db.models import ProactiveSignal, ProactiveSubscription, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def user_with_subs() -> str:
    import db.session as _session_mod
    await _session_mod._engine.dispose()

    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_test_poll_{suffix}"
    phone = f"+1888{suffix[:7]}"

    async with async_session() as session:
        u = User(
            id=user_id,
            phone=phone,
            name="poll test",
            timezone="UTC",
            living_profile={},
            created_at=_utcnow_naive(),
        )
        session.add(u)
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
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


def _make_sub(
    *, user_id: str, cadence: str, last_hit_at: datetime | None
) -> ProactiveSubscription:
    return ProactiveSubscription(
        user_id=user_id,
        intent_key=f"watch:{uuid.uuid4().hex[:8]}",
        description=f"test query {cadence}",
        cadence=cadence,
        created_at=_utcnow_naive(),
        last_refreshed_at=_utcnow_naive(),
        last_hit_at=last_hit_at,
        active=True,
    )


def test_is_due_returns_true_when_never_polled():
    sub = _make_sub(user_id="u", cadence="weekly", last_hit_at=None)
    assert _is_due(sub, _utcnow_naive()) is True


def test_is_due_returns_false_when_interval_not_elapsed():
    now = _utcnow_naive()
    # Polled 1 hour ago, cadence weekly: not due.
    sub = _make_sub(
        user_id="u", cadence="weekly", last_hit_at=now - timedelta(hours=1)
    )
    assert _is_due(sub, now) is False


def test_is_due_returns_true_when_interval_elapsed():
    now = _utcnow_naive()
    # Polled 8 days ago, cadence weekly (7d): due.
    sub = _make_sub(
        user_id="u", cadence="weekly", last_hit_at=now - timedelta(days=8)
    )
    assert _is_due(sub, now) is True


def test_is_due_handles_each_cadence():
    now = _utcnow_naive()
    for cadence, interval in _CADENCE_TO_INTERVAL.items():
        # Just under interval: not due
        sub_recent = _make_sub(
            user_id="u",
            cadence=cadence,
            last_hit_at=now - interval + timedelta(seconds=60),
        )
        assert _is_due(sub_recent, now) is False, f"{cadence} should not be due"
        # Just over interval: due
        sub_old = _make_sub(
            user_id="u",
            cadence=cadence,
            last_hit_at=now - interval - timedelta(seconds=60),
        )
        assert _is_due(sub_old, now) is True, f"{cadence} should be due"


def test_is_due_falls_back_to_weekly_for_unknown_cadence():
    now = _utcnow_naive()
    # 'gibberish' is unknown -> weekly default. 8d > 7d, so due.
    sub = _make_sub(
        user_id="u", cadence="gibberish", last_hit_at=now - timedelta(days=8)
    )
    assert _is_due(sub, now) is True
    # 6d < 7d, not due.
    sub2 = _make_sub(
        user_id="u", cadence="gibberish", last_hit_at=now - timedelta(days=6)
    )
    assert _is_due(sub2, now) is False


@pytest.mark.asyncio
async def test_poll_only_searches_due_subs(monkeypatch, user_with_subs):
    """Subs whose cadence hasn't elapsed must be skipped — that's the
    central cost-saving guarantee."""
    now = _utcnow_naive()
    async with async_session() as session:
        # Three subs: weekly (just polled, not due), daily (polled 2d ago, due),
        # weekly (never polled, due).
        s1 = _make_sub(
            user_id=user_with_subs,
            cadence="weekly",
            last_hit_at=now - timedelta(hours=2),
        )
        s2 = _make_sub(
            user_id=user_with_subs,
            cadence="daily",
            last_hit_at=now - timedelta(days=2),
        )
        s3 = _make_sub(
            user_id=user_with_subs,
            cadence="weekly",
            last_hit_at=None,
        )
        session.add_all([s1, s2, s3])
        await session.commit()

    # Capture every /search invocation. Return 0 results so we can
    # assert call counts cleanly without dealing with the enqueue path.
    search_calls: list[str] = []

    async def fake_search(query, **kwargs):
        search_calls.append(query)
        return {"results": []}

    monkeypatch.setattr(poller_mod, "exa_search", fake_search)
    monkeypatch.setattr(poller_mod, "have_exa_key", lambda: True)
    # Make sure the cost gate isn't tripping the test.
    monkeypatch.setenv("DONNA_EXA_AUTOMATION_PAUSE", "0")

    summary = await poll_pending_subscriptions(user_with_subs)

    # 2 due subs (s2, s3), 1 not due (s1).
    assert summary.polled == 2
    assert summary.failed == 0
    assert len(search_calls) == 2


@pytest.mark.asyncio
async def test_poll_bumps_last_hit_at_even_with_no_results(
    monkeypatch, user_with_subs
):
    """last_hit_at must update on every successful /search, not just
    when new URLs come back. Otherwise a sub that returns zero new
    results stays 'due' forever and we burn credits hourly on it.
    """
    now = _utcnow_naive()
    async with async_session() as session:
        sub = _make_sub(
            user_id=user_with_subs, cadence="daily", last_hit_at=None
        )
        session.add(sub)
        await session.commit()
        sub_id = sub.id

    async def fake_search(query, **kwargs):
        return {"results": []}  # no new URLs

    monkeypatch.setattr(poller_mod, "exa_search", fake_search)
    monkeypatch.setattr(poller_mod, "have_exa_key", lambda: True)
    monkeypatch.setenv("DONNA_EXA_AUTOMATION_PAUSE", "0")

    await poll_pending_subscriptions(user_with_subs)

    async with async_session() as session:
        refreshed = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.id == sub_id
                )
            )
        ).scalar_one()
    assert refreshed.last_hit_at is not None
    # And on the next poll within the cadence window, the sub is NOT
    # picked up again (cadence gate works end-to-end).
    summary = await poll_pending_subscriptions(user_with_subs)
    assert summary.polled == 0


@pytest.mark.asyncio
async def test_poll_no_op_when_paused(monkeypatch, user_with_subs):
    """DONNA_EXA_AUTOMATION_PAUSE=1 must short-circuit before any DB
    or Exa work — the emergency cost-stop guarantee.
    """
    async with async_session() as session:
        sub = _make_sub(
            user_id=user_with_subs, cadence="daily", last_hit_at=None
        )
        session.add(sub)
        await session.commit()

    search_calls: list[str] = []

    async def fake_search(query, **kwargs):
        search_calls.append(query)
        return {"results": []}

    monkeypatch.setattr(poller_mod, "exa_search", fake_search)
    monkeypatch.setattr(poller_mod, "have_exa_key", lambda: True)
    monkeypatch.setenv("DONNA_EXA_AUTOMATION_PAUSE", "1")

    summary = await poll_pending_subscriptions(user_with_subs)
    assert summary.polled == 0
    assert search_calls == []
