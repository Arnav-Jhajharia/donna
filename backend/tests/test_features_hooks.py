"""Tests for the feature post_observation hook dispatcher + the live
hydration handler ``update_hydration_state``.

End-to-end: log an observation, expect feature.state to update.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
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
    """Fixture that lets the real handlers register themselves.

    Unlike test_features_install.py we do NOT pre-register a noop —
    these tests exercise the actual handler.
    """
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
    from backend.features.registry import reset_registry_for_tests

    reset_registry_for_tests()
    _reset_handlers()
    # Re-register the real handlers explicitly. Module-level
    # registration only fires once per process; after _reset_handlers
    # we have to call register_handlers() again so the dispatcher can
    # find them.
    from backend.features.library._hydration_handlers import (
        register_handlers,
    )
    from backend.features.registry import get_registry

    register_handlers()
    get_registry()

    try:
        yield test_session
    finally:
        await engine.dispose()


# -- post_observation hook -------------------------------------------------


@pytest.mark.asyncio
async def test_logging_hydration_increments_today_count(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(user_id="u1", template_id="hydration_tracker")
    ).feature_id

    await log_observation(user_id="u1", type="hydration", fields={"glasses": 1})
    await log_observation(user_id="u1", type="hydration", fields={"glasses": 2})

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    assert feature.state.get("today_count") == 3
    assert feature.state.get("total_glasses") == 3
    assert feature.state.get("today_date")  # ISO date string
    assert "last_logged_at" in feature.state


@pytest.mark.asyncio
async def test_glasses_default_one_when_field_missing(db) -> None:
    """Hydration log without explicit count = one glass."""
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(user_id="u1", template_id="hydration_tracker")
    ).feature_id

    # No 'glasses' field at all.
    await log_observation(user_id="u1", type="hydration", fields={})

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    assert feature.state.get("today_count") == 1


@pytest.mark.asyncio
async def test_paused_feature_does_not_dispatch_hook(db) -> None:
    """Paused features are skipped by the dispatcher."""
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.lifecycle import pause_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(user_id="u1", template_id="hydration_tracker")
    ).feature_id
    await pause_feature(user_id="u1", template_id="hydration_tracker")

    await log_observation(user_id="u1", type="hydration", fields={"glasses": 1})

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    # State stays empty — the handler never ran while the feature was paused.
    assert feature.state == {}


@pytest.mark.asyncio
async def test_unrelated_observation_type_skips_dispatch(db) -> None:
    """Logging a 'meal' observation does not touch the hydration feature."""
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(user_id="u1", template_id="hydration_tracker")
    ).feature_id

    await log_observation(user_id="u1", type="meal", fields={"calories": 400})

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    assert feature.state == {}


# -- streak settling -------------------------------------------------------


@pytest.mark.asyncio
async def test_day_rollover_resets_today_count(db) -> None:
    """When event_time crosses the user-local day boundary, today_count
    resets and the previous day's count settles the streak.
    """
    from backend.features.install import install_feature
    from backend.features.library._hydration_handlers import (
        update_hydration_state,
    )
    from datetime import date, datetime, timezone
    from types import SimpleNamespace

    from backend.db.models import Feature
    from sqlalchemy import select

    feature_id = (
        await install_feature(
            user_id="u1",
            template_id="hydration_tracker",
            config_overrides={"target_glasses": 8},
        )
    ).feature_id

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        # Stage yesterday at-or-above-target so the streak should
        # increment on rollover.
        feature.state = {
            "today_count": 8,
            "today_date": "2026-05-04",
            "total_glasses": 8,
            "streak_days": 0,
        }
        await session.commit()

    # Event in user-local 2026-05-05 (rollover).
    obs = SimpleNamespace(
        type="hydration",
        fields={"glasses": 1},
        event_time=datetime(2026, 5, 5, 1, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None),
        # 01:00 UTC = 09:00 SGT, so local date = 2026-05-05.
    )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        await update_hydration_state(
            session=session, user_id="u1", feature=feature, obs=obs
        )
        await session.commit()

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    assert feature.state["today_count"] == 1
    assert feature.state["today_date"] == "2026-05-05"
    assert feature.state["total_glasses"] == 9
    # Yesterday (2026-05-04) hit the target of 8 → streak +1.
    assert feature.state["streak_days"] == 1
