"""Tests for ``render_evening_summary`` — the hydration cron handler.

The handler is a pure renderer over ``feature.state`` and
``feature.config`` — no DB writes — so most cases test it directly
with a stub feature object. One case verifies the schedule worker
actually calls the registered handler when a row's
``recurrence_meta.handler`` matches.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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

    from backend.features.handlers import _reset_for_tests as _reset_handlers
    from backend.features.registry import (
        get_registry,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    _reset_handlers()
    # Module-level registration in _hydration_handlers fires once per
    # process; after _reset_handlers we have to call register_handlers
    # again so the worker's handler-lookup finds the real one.
    from backend.features.library._hydration_handlers import (
        register_handlers,
    )

    register_handlers()
    get_registry()

    try:
        yield test_session
    finally:
        await engine.dispose()


def _today_in_sgt() -> str:
    return datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()


# -- render_evening_summary direct cases ----------------------------------


@pytest.mark.asyncio
async def test_evening_summary_silent_on_clean_miss(db) -> None:
    """No logs today → return None (don't nag)."""
    from backend.features.library._hydration_handlers import (
        render_evening_summary,
    )

    yesterday = (
        datetime.now(ZoneInfo("Asia/Singapore")) - timedelta(days=1)
    ).date().isoformat()
    feature = SimpleNamespace(
        state={"today_count": 0, "today_date": yesterday},
        config={"target_glasses": 8},
    )
    async with db() as session:
        out = await render_evening_summary(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is None


@pytest.mark.asyncio
async def test_evening_summary_target_hit_no_streak(db) -> None:
    from backend.features.library._hydration_handlers import (
        render_evening_summary,
    )

    feature = SimpleNamespace(
        state={
            "today_count": 8,
            "today_date": _today_in_sgt(),
            "streak_days": 0,
        },
        config={"target_glasses": 8},
    )
    async with db() as session:
        out = await render_evening_summary(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out and "target hit" in out


@pytest.mark.asyncio
async def test_evening_summary_target_hit_with_streak(db) -> None:
    from backend.features.library._hydration_handlers import (
        render_evening_summary,
    )

    feature = SimpleNamespace(
        state={
            "today_count": 10,
            "today_date": _today_in_sgt(),
            "streak_days": 4,
        },
        config={"target_glasses": 8},
    )
    async with db() as session:
        out = await render_evening_summary(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out and "4-day streak" in out


@pytest.mark.asyncio
async def test_evening_summary_one_short_phrasing(db) -> None:
    from backend.features.library._hydration_handlers import (
        render_evening_summary,
    )

    feature = SimpleNamespace(
        state={
            "today_count": 7,
            "today_date": _today_in_sgt(),
            "streak_days": 0,
        },
        config={"target_glasses": 8},
    )
    async with db() as session:
        out = await render_evening_summary(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out and "one short" in out


@pytest.mark.asyncio
async def test_evening_summary_multi_short_phrasing(db) -> None:
    from backend.features.library._hydration_handlers import (
        render_evening_summary,
    )

    feature = SimpleNamespace(
        state={
            "today_count": 3,
            "today_date": _today_in_sgt(),
            "streak_days": 0,
        },
        config={"target_glasses": 8},
    )
    async with db() as session:
        out = await render_evening_summary(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out and "5 short" in out


# -- worker integration ----------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_worker_calls_feature_cron_handler(db) -> None:
    """Worker's _maybe_render_feature_cron resolves the registered handler
    and uses its body when present.
    """
    from backend.db.models import DonnaSchedule
    from backend.features.install import install_feature
    from backend.memory.jobs.schedule_worker import _maybe_render_feature_cron
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(user_id="u1", template_id="hydration_tracker")
    ).feature_id
    # Drive state into "target hit, no streak" so the handler returns
    # the "target hit. nice." branch.
    for _ in range(8):
        await log_observation(
            user_id="u1", type="hydration", fields={"glasses": 1}
        )

    async with db() as session:
        from sqlalchemy import select

        sched = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id
                )
            )
        ).scalar_one()

    body = await _maybe_render_feature_cron(sched)
    assert body and "target hit" in body
