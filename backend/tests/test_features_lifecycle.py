"""Tests for ``backend.features.lifecycle`` — pause / resume / archive /
list / update_feature_config.

Each test exercises the full transition: feature row + linked attentions
+ linked schedules. The fixture mirrors test_features_install.py so the
same in-memory SQLite + monkeypatched async_session pattern is shared.
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


async def _noop(*args, **kwargs) -> None:
    return None


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
    from backend.features.handlers import register_cron_handler
    from backend.features.registry import reset_registry_for_tests

    reset_registry_for_tests()
    _reset_handlers()
    # Register the hydration cron handler so install materialises a
    # schedule row (which lifecycle then has to clean up).
    register_cron_handler("render_evening_summary", _noop)

    try:
        yield test_session
    finally:
        await engine.dispose()


async def _install_hydration(*, target_glasses: int = 8) -> str:
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1",
        template_id="hydration_tracker",
        config_overrides={"target_glasses": target_glasses},
    )
    return result.feature_id


# -- pause -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_feature_paused_status_and_attentions(db) -> None:
    from backend.db.models import AttentionRow, DonnaSchedule, Feature
    from backend.features.lifecycle import pause_feature

    feature_id = await _install_hydration()

    feature = await pause_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert feature is not None
    assert feature.id == feature_id
    assert feature.status == "paused"

    async with db() as session:
        atts = (
            await session.execute(
                select(AttentionRow).where(
                    AttentionRow.feature_id == feature_id
                )
            )
        ).scalars().all()
    assert atts
    for a in atts:
        assert a.status == "paused"

    async with db() as session:
        schs = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id
                )
            )
        ).scalars().all()
    assert schs
    for s in schs:
        assert s.fired is True
        assert s.status == "skipped"
        assert s.last_error == "feature_paused"


@pytest.mark.asyncio
async def test_pause_feature_idempotent(db) -> None:
    from backend.features.lifecycle import pause_feature

    await _install_hydration()
    a = await pause_feature(user_id="u1", template_id="hydration_tracker")
    b = await pause_feature(user_id="u1", template_id="hydration_tracker")
    assert a is not None and b is not None
    assert a.status == b.status == "paused"


@pytest.mark.asyncio
async def test_pause_feature_unknown_returns_none(db) -> None:
    from backend.features.lifecycle import pause_feature

    feature = await pause_feature(
        user_id="u1", template_id="not_installed"
    )
    assert feature is None


# -- resume ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_feature_flips_status_and_attentions(db) -> None:
    from backend.db.models import AttentionRow
    from backend.features.lifecycle import pause_feature, resume_feature

    feature_id = await _install_hydration()
    await pause_feature(user_id="u1", template_id="hydration_tracker")

    feature = await resume_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert feature is not None
    assert feature.status == "active"
    assert feature.paused_until is None

    async with db() as session:
        atts = (
            await session.execute(
                select(AttentionRow).where(
                    AttentionRow.feature_id == feature_id
                )
            )
        ).scalars().all()
    for a in atts:
        # Feature-spawned rows go back to live; manual-paused rows would
        # stay paused but we don't have any in this fixture.
        assert a.status == "live"


@pytest.mark.asyncio
async def test_resume_re_materialises_cron(db) -> None:
    """Resume should enqueue a fresh future schedule row.

    The pause-window's ``skipped`` rows stay skipped (audit trail), but a
    fresh ``pending`` row covers the next fire so the cron survives the
    pause.
    """
    from backend.db.models import DonnaSchedule
    from backend.features.lifecycle import pause_feature, resume_feature

    feature_id = await _install_hydration()

    async with db() as session:
        before = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id
                )
            )
        ).scalars().all()
    assert len(before) == 1

    await pause_feature(user_id="u1", template_id="hydration_tracker")
    await resume_feature(user_id="u1", template_id="hydration_tracker")

    async with db() as session:
        after = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id
                )
            )
        ).scalars().all()
    pending = [s for s in after if s.status == "pending" and not s.fired]
    skipped = [s for s in after if s.status == "skipped" and s.fired]
    assert len(pending) == 1
    assert len(skipped) == 1


# -- archive ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_feature_quietly_archives(db) -> None:
    from backend.db.models import AttentionRow, DonnaSchedule
    from backend.features.lifecycle import archive_feature

    feature_id = await _install_hydration()

    feature = await archive_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert feature is not None
    assert feature.status == "archived"

    async with db() as session:
        atts = (
            await session.execute(
                select(AttentionRow).where(
                    AttentionRow.feature_id == feature_id
                )
            )
        ).scalars().all()
    for a in atts:
        assert a.status == "quietly_archived"

    async with db() as session:
        schs = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.feature_id == feature_id
                )
            )
        ).scalars().all()
    for s in schs:
        assert s.fired is True
        assert s.status == "skipped"
        assert s.last_error == "feature_archived"


@pytest.mark.asyncio
async def test_archive_feature_preserves_observations(db) -> None:
    """Archive must not delete observation rows — historical data is the
    point of feature_id back-links. Uses ``log_observation`` so the
    DonnaInstance row is auto-created via the real write path.
    """
    from backend.db.models import Observation
    from backend.features.lifecycle import archive_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = await _install_hydration()

    res = await log_observation(
        user_id="u1",
        type="hydration",
        fields={"glasses": 1},
    )
    assert res["status"] == "ok"

    await archive_feature(user_id="u1", template_id="hydration_tracker")

    async with db() as session:
        obs = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()
    assert len(obs) == 1
    assert obs[0].feature_id == feature_id


# -- list ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_features_returns_active(db) -> None:
    from backend.features.lifecycle import list_features

    await _install_hydration()
    rows = await list_features(user_id="u1")
    assert len(rows) == 1
    assert rows[0].template_id == "hydration_tracker"
    assert rows[0].status == "active"


@pytest.mark.asyncio
async def test_list_features_status_filter(db) -> None:
    from backend.features.lifecycle import (
        list_features,
        pause_feature,
    )

    await _install_hydration()
    await pause_feature(user_id="u1", template_id="hydration_tracker")

    active = await list_features(user_id="u1", status="active")
    paused = await list_features(user_id="u1", status="paused")
    assert active == []
    assert len(paused) == 1


@pytest.mark.asyncio
async def test_list_features_empty_when_none_installed(db) -> None:
    from backend.features.lifecycle import list_features

    rows = await list_features(user_id="u1")
    assert rows == []


# -- update_feature_config -------------------------------------------------


@pytest.mark.asyncio
async def test_update_feature_config_merges_patch(db) -> None:
    from backend.features.lifecycle import update_feature_config

    await _install_hydration(target_glasses=8)

    feature = await update_feature_config(
        user_id="u1",
        template_id="hydration_tracker",
        config_patch={"target_glasses": 12},
    )
    assert feature is not None
    assert feature.config["target_glasses"] == 12
    # Other defaults preserved.
    assert feature.config["remind_every_min"] == 120


@pytest.mark.asyncio
async def test_update_feature_config_unknown_key_rejected(db) -> None:
    from backend.features.lifecycle import update_feature_config

    await _install_hydration()

    with pytest.raises(ValueError, match="unknown config key"):
        await update_feature_config(
            user_id="u1",
            template_id="hydration_tracker",
            config_patch={"not_a_real_key": 99},
        )


@pytest.mark.asyncio
async def test_update_feature_config_clamps_to_bounds(db) -> None:
    """Manifest declares target_glasses min=1, max=30. 999 should clamp to 30."""
    from backend.features.lifecycle import update_feature_config

    await _install_hydration()

    feature = await update_feature_config(
        user_id="u1",
        template_id="hydration_tracker",
        config_patch={"target_glasses": 999},
    )
    assert feature is not None
    assert feature.config["target_glasses"] == 30


@pytest.mark.asyncio
async def test_update_feature_config_unknown_feature_returns_none(db) -> None:
    from backend.features.lifecycle import update_feature_config

    feature = await update_feature_config(
        user_id="u1",
        template_id="not_installed",
        config_patch={"target_glasses": 10},
    )
    assert feature is None
