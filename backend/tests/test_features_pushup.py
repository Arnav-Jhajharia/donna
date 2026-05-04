"""Tests for the Push-up tracker — Tier B+ reactive feature.

This feature exercises the subscriber-observation pattern: a workout
observation triggers a delayed Donna prompt via a one-shot
DonnaSchedule, while pushup observations themselves update state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from zoneinfo import ZoneInfo

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
    from backend.features.library._pushup_handlers import (
        register_handlers as register_pushup,
    )

    register_pushup()
    get_registry()

    try:
        yield test_session
    finally:
        await engine.dispose()


# -- Install ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_pushup_creates_feature_with_weekly_recap(db) -> None:
    from backend.db.models import DonnaSchedule, Feature
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    assert result.created is True
    assert len(result.attention_ids) == 0   # reactive feature, no attention rows
    assert len(result.schedule_ids) == 1    # only the weekly recap pre-materialises

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
        sched = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == result.feature_id
                )
            )
        ).scalar_one()

    assert feature.surface == "body"
    assert feature.tone == "rust"
    assert sched.recurrence_meta["handler"] == "render_pushup_weekly_recap"


# -- Reactive prompt path --------------------------------------------------


@pytest.mark.asyncio
async def test_workout_observation_queues_prompt(db) -> None:
    """Logging a workout creates a pending DonnaSchedule with the prompt handler."""
    from backend.db.models import DonnaSchedule
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    feature_id = result.feature_id

    async with db() as session:
        before = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id,
                    DonnaSchedule.recurrence_meta["handler"].as_string()
                    == "render_pushup_prompt",
                )
            )
        ).scalars().all()
    assert before == []

    await log_observation(
        user_id="u1", type="workout", fields={"kind": "strength"}
    )

    async with db() as session:
        prompts = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id,
                    DonnaSchedule.fired.is_(False),
                )
            )
        ).scalars().all()
    # Two pending: weekly recap (created on install) + new prompt fire.
    handlers = sorted(
        (s.recurrence_meta or {}).get("handler") for s in prompts
    )
    assert "render_pushup_prompt" in handlers


@pytest.mark.asyncio
async def test_workout_observation_dedups_pending_prompt(db) -> None:
    """A second workout while a prompt is still pending doesn't queue another."""
    from backend.db.models import DonnaSchedule
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    feature_id = result.feature_id

    await log_observation(
        user_id="u1", type="workout", fields={"kind": "strength"}
    )
    await log_observation(
        user_id="u1", type="workout", fields={"kind": "strength"}
    )

    async with db() as session:
        prompt_rows = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id,
                )
            )
        ).scalars().all()

    prompt_handlers = [
        s for s in prompt_rows
        if (s.recurrence_meta or {}).get("handler") == "render_pushup_prompt"
    ]
    assert len(prompt_handlers) == 1


@pytest.mark.asyncio
async def test_workout_skips_prompt_when_pushup_logged_recently(db) -> None:
    """If the user already self-reported push-ups in the last hour, no prompt."""
    from backend.db.models import DonnaSchedule
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    feature_id = result.feature_id

    # Self-reported push-ups first.
    await log_observation(
        user_id="u1", type="pushup", fields={"reps": 25}
    )
    # Then a workout — prompt should be suppressed.
    await log_observation(
        user_id="u1", type="workout", fields={"kind": "strength"}
    )

    async with db() as session:
        prompts = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id,
                )
            )
        ).scalars().all()
    handlers = [
        (s.recurrence_meta or {}).get("handler") for s in prompts
    ]
    assert "render_pushup_prompt" not in handlers


# -- State-update path -----------------------------------------------------


@pytest.mark.asyncio
async def test_pushup_observation_updates_state(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    feature_id = result.feature_id

    await log_observation(user_id="u1", type="pushup", fields={"reps": 25})
    await log_observation(user_id="u1", type="pushup", fields={"reps": 30})
    await log_observation(user_id="u1", type="pushup", fields={"reps": 18})

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()

    assert feature.state["today_count"] == 73   # 25+30+18
    assert feature.state["week_count"] == 73
    assert feature.state["total_count"] == 73
    assert feature.state["pr"] == 30            # max of (25, 30, 18)


@pytest.mark.asyncio
async def test_workout_observation_does_not_update_state_counters(db) -> None:
    """Workouts trigger the prompt hook but NOT update_pushup_state."""
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    feature_id = result.feature_id

    await log_observation(
        user_id="u1", type="workout", fields={"kind": "strength"}
    )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    # State has nothing — workout shouldn't bump counters.
    assert feature.state.get("today_count") in (None, 0)
    assert feature.state.get("total_count") in (None, 0)


# -- Prompt rendering ------------------------------------------------------


@pytest.mark.asyncio
async def test_render_prompt_returns_one_of_variants(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._pushup_handlers import (
        _PROMPT_VARIANTS,
        render_pushup_prompt,
    )

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
        out = await render_pushup_prompt(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out in _PROMPT_VARIANTS


# -- Weekly recap ----------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_recap_silent_with_no_entries(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._pushup_handlers import (
        render_pushup_weekly_recap,
    )

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )
    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
        out = await render_pushup_weekly_recap(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is None


@pytest.mark.asyncio
async def test_weekly_recap_includes_count_and_pr(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._pushup_handlers import (
        render_pushup_weekly_recap,
    )
    from backend.memory.tools.log_observation import log_observation

    result = await install_feature(
        user_id="u1", template_id="pushup_tracker"
    )

    for reps in (40, 50, 35):
        await log_observation(
            user_id="u1", type="pushup", fields={"reps": reps}
        )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
        out = await render_pushup_weekly_recap(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is not None
    assert "125" in out          # 40+50+35
    assert "PR: 50" in out
