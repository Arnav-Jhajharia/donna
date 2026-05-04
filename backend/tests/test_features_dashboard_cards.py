"""Tests for ``backend.features.dashboard_cards``.

Covers:
  - feature flag gate (off / global / per-user)
  - placeholder hydration in fill templates
  - state derivation from the composer's observations list
  - candidate ordering by priority
"""
from __future__ import annotations

from datetime import datetime, timedelta
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

    from backend.features.handlers import (
        _reset_for_tests as _reset_handlers,
        register_cron_handler,
    )
    from backend.features.registry import reset_registry_for_tests

    reset_registry_for_tests()
    _reset_handlers()
    register_cron_handler("render_evening_summary", _noop)

    try:
        yield test_session
    finally:
        await engine.dispose()


# -- Feature flag ----------------------------------------------------------


def test_feature_dashboard_flag_default_off(monkeypatch) -> None:
    from backend.features.dashboard_cards import is_feature_dashboard_enabled

    monkeypatch.delenv("DONNA_FEATURE_DASHBOARD_CARDS", raising=False)
    assert is_feature_dashboard_enabled() is False
    assert is_feature_dashboard_enabled("u1") is False


def test_feature_dashboard_flag_global_on(monkeypatch) -> None:
    from backend.features.dashboard_cards import is_feature_dashboard_enabled

    monkeypatch.setenv("DONNA_FEATURE_DASHBOARD_CARDS", "1")
    assert is_feature_dashboard_enabled() is True
    assert is_feature_dashboard_enabled("anybody") is True


def test_feature_dashboard_flag_user_scoped(monkeypatch) -> None:
    from backend.features.dashboard_cards import is_feature_dashboard_enabled

    monkeypatch.setenv("DONNA_FEATURE_DASHBOARD_CARDS", "u1")
    assert is_feature_dashboard_enabled("u1") is True
    assert is_feature_dashboard_enabled("u2") is False
    assert is_feature_dashboard_enabled() is False


# -- Placeholder hydration -------------------------------------------------


def test_hydrate_str_pure_placeholder_returns_value() -> None:
    from backend.features.dashboard_cards import _hydrate_str

    out = _hydrate_str(
        "{state.today_count}", state={"today_count": 3}, config={}
    )
    assert out == 3


def test_hydrate_str_mixed_returns_string() -> None:
    from backend.features.dashboard_cards import _hydrate_str

    out = _hydrate_str(
        "{state.today_count}/{config.target_glasses}",
        state={"today_count": 3},
        config={"target_glasses": 8},
    )
    assert out == "3/8"


def test_hydrate_str_unknown_token_left_alone() -> None:
    from backend.features.dashboard_cards import _hydrate_str

    out = _hydrate_str(
        "{state.what_is_this}", state={}, config={}
    )
    # Pure-placeholder unknown returns the raw template string by default.
    assert out == "{state.what_is_this}"


def test_hydrate_str_no_placeholders_passthrough() -> None:
    from backend.features.dashboard_cards import _hydrate_str

    out = _hydrate_str("water", state={}, config={})
    assert out == "water"


# -- State + candidates ----------------------------------------------------


@pytest.mark.asyncio
async def test_read_feature_card_candidates_hydrates_state(db) -> None:
    """Hydration card.value reflects today's observation count."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.dashboard_cards import read_feature_card_candidates
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    feature_id = (
        await install_feature(
            user_id="u1",
            template_id="hydration_tracker",
            config_overrides={"target_glasses": 10},
        )
    ).feature_id

    # Log 3 hydration observations through the canonical write path so
    # DonnaInstance + feature_id auto-tagging happen correctly.
    for _ in range(3):
        await log_observation(
            user_id="u1", type="hydration", fields={"glasses": 1}
        )

    async with db() as session:
        obs = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()

    # Bend the events into "today" relative to the chosen now_local. The
    # ``log_observation`` path stamps event_time = utcnow(); we need them
    # to fall on the same local date as ``now_local`` for the count to
    # match.
    now_local = datetime.utcnow().replace(microsecond=0)

    async with db() as session:
        cards = await read_feature_card_candidates(
            session=session,
            user_id="u1",
            observations=list(obs),
            now_local=now_local,
        )

    assert cards, "expected at least one card"
    tracker = next(c for c in cards if c.archetype == "c-tracker")
    assert tracker.fill["value"] == 3
    assert tracker.fill["target"] == 10
    assert tracker.feature_id == feature_id
    assert tracker.feature_template_id == "hydration_tracker"


@pytest.mark.asyncio
async def test_candidates_empty_when_no_active_features(db) -> None:
    from backend.features.dashboard_cards import read_feature_card_candidates

    async with db() as session:
        cards = await read_feature_card_candidates(
            session=session,
            user_id="u1",
            observations=[],
            now_local=datetime(2026, 5, 5, 18, 0, 0),
        )
    assert cards == []


@pytest.mark.asyncio
async def test_candidates_excluded_when_paused(db) -> None:
    from backend.features.dashboard_cards import read_feature_card_candidates
    from backend.features.install import install_feature
    from backend.features.lifecycle import pause_feature

    await install_feature(user_id="u1", template_id="hydration_tracker")
    await pause_feature(user_id="u1", template_id="hydration_tracker")

    async with db() as session:
        cards = await read_feature_card_candidates(
            session=session,
            user_id="u1",
            observations=[],
            now_local=datetime(2026, 5, 5, 18, 0, 0),
        )
    assert cards == []


@pytest.mark.asyncio
async def test_brief_line_format(db) -> None:
    """Brief line format is compact and includes feature_id back-link."""
    from backend.features.dashboard_cards import read_feature_card_candidates
    from backend.features.install import install_feature

    await install_feature(user_id="u1", template_id="hydration_tracker")

    async with db() as session:
        cards = await read_feature_card_candidates(
            session=session,
            user_id="u1",
            observations=[],
            now_local=datetime(2026, 5, 5, 18, 0, 0),
        )
    line = cards[0].to_brief_line()
    assert "c-tracker" in line
    assert "feature=hydration_tracker" in line
    assert "priority=" in line
