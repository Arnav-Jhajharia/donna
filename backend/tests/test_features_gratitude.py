"""Tests for the Gratitude feature (Tier B reference manifest).

Validates the abstraction generalises beyond Hydration:
- different shape (cron + reflection vs counter + tracker)
- empty ``attentions`` array
- two crons in one manifest
- new observation type owned by a different feature
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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

    from backend.features.library._gratitude_handlers import (
        register_handlers as register_gratitude,
    )
    from backend.features.library._hydration_handlers import (
        register_handlers as register_hydration,
    )

    register_gratitude()
    register_hydration()
    get_registry()

    try:
        yield test_session
    finally:
        await engine.dispose()


# -- Install ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_gratitude_creates_feature_with_two_crons(db) -> None:
    from backend.db.models import DonnaSchedule, Feature
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="gratitude_practice"
    )
    assert result.created is True
    assert len(result.attention_ids) == 0  # no attentions in this manifest
    assert len(result.schedule_ids) == 2   # nightly prompt + weekly recap

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
    assert feature.surface == "mind"
    assert feature.icon == "heart"
    assert feature.tone == "amber"
    assert feature.config["prompt_time"] == "21:30"

    async with db() as session:
        schs = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == result.feature_id
                )
            )
        ).scalars().all()
    handlers = sorted((s.recurrence_meta or {}).get("handler") for s in schs)
    assert handlers == [
        "render_gratitude_prompt",
        "render_gratitude_weekly_recap",
    ]


@pytest.mark.asyncio
async def test_install_gratitude_alongside_hydration(db) -> None:
    """Both features can be installed for the same user simultaneously."""
    from backend.db.models import Feature
    from backend.features.install import install_feature

    a = await install_feature(user_id="u1", template_id="hydration_tracker")
    b = await install_feature(user_id="u1", template_id="gratitude_practice")
    assert a.feature_id != b.feature_id

    async with db() as session:
        rows = (
            await session.execute(
                select(Feature).where(Feature.user_id == "u1")
            )
        ).scalars().all()
    assert {r.template_id for r in rows} == {
        "hydration_tracker",
        "gratitude_practice",
    }


# -- Auto-tagging across features ------------------------------------------


@pytest.mark.asyncio
async def test_gratitude_observation_tags_correct_feature(db) -> None:
    """Gratitude observation must tag the gratitude feature, not hydration."""
    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    hyd = await install_feature(user_id="u1", template_id="hydration_tracker")
    grat = await install_feature(
        user_id="u1", template_id="gratitude_practice"
    )

    await log_observation(
        user_id="u1",
        type="gratitude",
        fields={"note": "test gratitude entry"},
    )
    await log_observation(
        user_id="u1", type="hydration", fields={"glasses": 1}
    )

    async with db() as session:
        rows = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()
    by_type = {o.type: o for o in rows}
    assert by_type["gratitude"].feature_id == grat.feature_id
    assert by_type["hydration"].feature_id == hyd.feature_id


# -- post_observation hook -------------------------------------------------


@pytest.mark.asyncio
async def test_logging_gratitude_updates_state(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(
            user_id="u1", template_id="gratitude_practice"
        )
    ).feature_id

    await log_observation(
        user_id="u1",
        type="gratitude",
        fields={"note": "the rain stopped at exactly the right moment"},
    )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
    assert feature.state.get("today_count") == 1
    assert feature.state.get("week_count") == 1
    assert feature.state.get("today_date")  # ISO date


# -- Cron handlers ---------------------------------------------------------


@pytest.mark.asyncio
async def test_nightly_prompt_silent_when_already_logged(db) -> None:
    """If the user already wrote a gratitude entry today, skip the prompt."""
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._gratitude_handlers import (
        render_gratitude_prompt,
    )
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(
            user_id="u1", template_id="gratitude_practice"
        )
    ).feature_id
    await log_observation(
        user_id="u1", type="gratitude", fields={"note": "early bird"}
    )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        out = await render_gratitude_prompt(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is None


@pytest.mark.asyncio
async def test_nightly_prompt_returns_one_of_variants(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._gratitude_handlers import (
        _PROMPT_VARIANTS,
        render_gratitude_prompt,
    )

    feature_id = (
        await install_feature(
            user_id="u1", template_id="gratitude_practice"
        )
    ).feature_id

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        out = await render_gratitude_prompt(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out in _PROMPT_VARIANTS


@pytest.mark.asyncio
async def test_weekly_recap_skips_when_no_entries(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._gratitude_handlers import (
        render_gratitude_weekly_recap,
    )

    feature_id = (
        await install_feature(
            user_id="u1", template_id="gratitude_practice"
        )
    ).feature_id

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        out = await render_gratitude_weekly_recap(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is None


@pytest.mark.asyncio
async def test_weekly_recap_with_entries_returns_count(db) -> None:
    from backend.db.models import Feature
    from backend.features.install import install_feature
    from backend.features.library._gratitude_handlers import (
        render_gratitude_weekly_recap,
    )
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(
            user_id="u1", template_id="gratitude_practice"
        )
    ).feature_id

    for note in ("first thing", "second thing", "third thing"):
        await log_observation(
            user_id="u1", type="gratitude", fields={"note": note}
        )

    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one()
        out = await render_gratitude_weekly_recap(
            session=session,
            user_id="u1",
            feature=feature,
            schedule_row=None,
        )
    assert out is not None
    assert "3" in out  # the count


# -- Recipe surfacing ------------------------------------------------------


@pytest.mark.asyncio
async def test_gratitude_install_filters_its_recipe(db) -> None:
    """Once installed, the gratitude recipe should drop out of the mosaic."""
    from backend.dashboard.recipe_selector import _existing_capabilities
    from backend.features.install import install_feature

    before = await _existing_capabilities("u1")
    assert "gratitude_practice" not in before

    await install_feature(user_id="u1", template_id="gratitude_practice")

    after = await _existing_capabilities("u1")
    assert "gratitude_practice" in after
