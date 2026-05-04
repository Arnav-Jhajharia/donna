"""Tests for log_observation auto-tagging with feature_id.

When a user has an active feature claiming an observation type, new
observations of that type must carry feature_id on insert. Other
observations stay NULL exactly like the pre-feature world.
"""
from __future__ import annotations

from typing import AsyncIterator

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
        s.add(User(id="u2", phone="+15557654321", timezone="Asia/Singapore"))
        await s.commit()

    import backend.db.session as backend_session
    import db.session as root_session

    monkeypatch.setattr(root_session, "async_session", test_session)
    monkeypatch.setattr(backend_session, "async_session", test_session)

    from backend.features.registry import reset_registry_for_tests

    reset_registry_for_tests()

    # Stub the situation-brief refresh + attention re-eval calls so the
    # test focuses on the feature_id wiring without dragging the rest
    # of the pipeline along. Both helpers are best-effort in production.
    import backend.memory.tools.log_observation as log_obs_module

    async def _noop_refresh(_: str) -> bool:
        return False

    async def _noop_reeval(**_: object) -> None:
        return None

    monkeypatch.setattr(
        log_obs_module, "_refresh_situation_brief", _noop_refresh
    )
    monkeypatch.setattr(
        log_obs_module, "_reevaluate_attentions", _noop_reeval
    )

    try:
        yield test_session
    finally:
        await engine.dispose()


# -- Auto-tagging happy path ------------------------------------------------


@pytest.mark.asyncio
async def test_log_observation_tags_feature_id_when_active_feature_matches(
    db,
) -> None:
    """A hydration log after install must carry feature_id."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    install_result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    result = await log_observation(
        user_id="u1",
        type="hydration",
        fields={"glasses": 2},
        raw="had two glasses of water",
    )
    assert result["status"] == "ok"

    async with db() as session:
        rows = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].feature_id == install_result.feature_id
    assert rows[0].type == "hydration"


@pytest.mark.asyncio
async def test_log_observation_leaves_feature_id_null_for_unowned_type(
    db,
) -> None:
    """A meal log without an installed feature must stay NULL."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    # Install hydration so the registry is loaded; meal is reserved but
    # no system feature owns it yet, so it is unowned at log time.
    await install_feature(user_id="u1", template_id="hydration_tracker")

    result = await log_observation(
        user_id="u1",
        type="meal",
        fields={"calories": 400},
    )
    assert result["status"] == "ok"

    async with db() as session:
        row = (
            await session.execute(
                select(Observation).where(Observation.type == "meal")
            )
        ).scalar_one()
    assert row.feature_id is None


@pytest.mark.asyncio
async def test_log_observation_leaves_feature_id_null_when_user_has_no_feature(
    db,
) -> None:
    """User u2 hasn't installed hydration → log stays untagged."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    # u1 installs the feature, but u2 logs.
    await install_feature(user_id="u1", template_id="hydration_tracker")

    result = await log_observation(
        user_id="u2",
        type="hydration",
        fields={"glasses": 1},
    )
    assert result["status"] == "ok"

    async with db() as session:
        row = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u2")
            )
        ).scalar_one()
    assert row.feature_id is None


@pytest.mark.asyncio
async def test_log_observation_leaves_feature_id_null_when_feature_paused(
    db,
) -> None:
    """A feature with status != active must not auto-tag observations."""
    from sqlalchemy import select

    from backend.db.models import Feature, Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    install_result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    # Manually flip status to paused to simulate the Phase 2 lifecycle.
    async with db() as session:
        feature = (
            await session.execute(
                select(Feature).where(Feature.id == install_result.feature_id)
            )
        ).scalar_one()
        feature.status = "paused"
        await session.commit()

    result = await log_observation(
        user_id="u1",
        type="hydration",
        fields={"glasses": 1},
    )
    assert result["status"] == "ok"

    async with db() as session:
        row = (
            await session.execute(
                select(Observation).where(
                    Observation.user_id == "u1",
                    Observation.type == "hydration",
                )
            )
        ).scalar_one()
    assert row.feature_id is None


@pytest.mark.asyncio
async def test_log_observation_does_not_tag_unknown_observation_type(
    db,
) -> None:
    """Free-form log of an unknown type must keep working untagged."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    await install_feature(user_id="u1", template_id="hydration_tracker")

    result = await log_observation(
        user_id="u1",
        type="custom_unowned_type",
        fields={"value": 1},
    )
    assert result["status"] == "ok"

    async with db() as session:
        row = (
            await session.execute(
                select(Observation).where(
                    Observation.type == "custom_unowned_type"
                )
            )
        ).scalar_one()
    assert row.feature_id is None
