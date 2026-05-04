"""Tests for ``backend.features.install.install_feature``.

Idempotency, attention spawning, cron materialisation, FK tagging, and
the missing-integration block path.
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
    """In-memory SQLite + monkeypatched async_session.

    The features registry is reset before each test so library load is
    fresh and tests don't share template state.
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

    try:
        yield test_session
    finally:
        await engine.dispose()


async def _noop_cron_handler(*args, **kwargs) -> None:
    """Test helper: stand-in for a real cron handler so install can
    materialise schedule rows. Tests that need to assert the gating
    behavior pre-register nothing instead.
    """
    return None


# -- Happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_creates_feature_row(db) -> None:
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert result.created is True
    assert result.feature_id

    async with db() as session:
        row = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
    assert row.user_id == "u1"
    assert row.template_id == "hydration_tracker"
    assert row.name == "Hydration"
    assert row.status == "active"
    assert row.surface == "body"
    assert row.config["target_glasses"] == 8
    assert row.config["remind_every_min"] == 120


@pytest.mark.asyncio
async def test_install_feature_applies_config_overrides(db) -> None:
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1",
        template_id="hydration_tracker",
        config_overrides={"target_glasses": 10},
    )

    async with db() as session:
        row = (
            await session.execute(
                select(Feature).where(Feature.id == result.feature_id)
            )
        ).scalar_one()
    assert row.config["target_glasses"] == 10
    # Defaults from manifest survive for keys not overridden.
    assert row.config["remind_every_min"] == 120


@pytest.mark.asyncio
async def test_install_feature_is_idempotent(db) -> None:
    """Re-installing same template for same user is a no-op."""
    from sqlalchemy import func, select

    from backend.db.models import Feature
    from backend.features.install import install_feature

    first = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    second = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert first.feature_id == second.feature_id
    assert first.created is True
    assert second.created is False

    async with db() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Feature).where(
                    Feature.user_id == "u1"
                )
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_install_feature_re_install_does_not_clobber_config(db) -> None:
    """Idempotent re-install with new overrides must not touch existing config."""
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.features.install import install_feature

    await install_feature(
        user_id="u1",
        template_id="hydration_tracker",
        config_overrides={"target_glasses": 12},
    )
    await install_feature(
        user_id="u1",
        template_id="hydration_tracker",
        config_overrides={"target_glasses": 99},
    )

    async with db() as session:
        row = (
            await session.execute(
                select(Feature).where(Feature.template_id == "hydration_tracker")
            )
        ).scalar_one()
    # First install's overrides win; second install is a no-op.
    assert row.config["target_glasses"] == 12


# -- Attention spawning -----------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_spawns_two_attentions(db) -> None:
    """Hydration manifest declares tally + ping → two AttentionRows."""
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert len(result.attention_ids) == 2

    async with db() as session:
        rows = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.user_id == "u1")
            )
        ).scalars().all()

    assert len(rows) == 2
    cards = sorted(r.card for r in rows)
    assert cards == ["ping", "tally"]
    for row in rows:
        assert row.feature_id == result.feature_id
        assert row.status == "live"


@pytest.mark.asyncio
async def test_attention_payload_carries_feature_metadata(db) -> None:
    """The spawned row's payload must round-trip identifying info."""
    from sqlalchemy import select

    from backend.db.models import AttentionRow
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    async with db() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(
                    AttentionRow.user_id == "u1",
                    AttentionRow.card == "ping",
                )
            )
        ).scalar_one()

    payload = row.payload
    assert payload["feature_id"] == result.feature_id
    assert payload["feature_template_id"] == "hydration_tracker"
    assert payload["card"] == "ping"
    assert payload["cadence_template"] == "every_N_minutes"
    assert payload["cadence_param_key"] == "remind_every_min"
    assert payload["spawned_by"] == "feature_install"


# -- Cron materialisation ---------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_materialises_cron(db) -> None:
    """One cron entry → one DonnaSchedule row tagged with feature_id."""
    from sqlalchemy import select

    from backend.db.models import DonnaSchedule
    from backend.features.handlers import register_cron_handler
    from backend.features.install import install_feature

    register_cron_handler("render_evening_summary", _noop_cron_handler)

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert len(result.schedule_ids) == 1

    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    schedule = rows[0]
    assert schedule.feature_id == result.feature_id
    assert schedule.recurrence == "daily"
    assert schedule.recurrence_meta["cron_name"] == "evening_summary"
    assert schedule.recurrence_meta["cron_expr"] == "0 21 * * *"
    assert schedule.recurrence_meta["feature_id"] == result.feature_id


@pytest.mark.asyncio
async def test_install_feature_skips_cron_when_handler_unregistered(
    db,
) -> None:
    """No registered handler → no schedule row, no silent literal-text fire.

    The schedule worker's else-branch (no attention_id, no
    context.messages) falls through to ``[{"type":"text","body":"reminder"}]``
    which would WhatsApp the literal word "reminder" to the user. Refuse
    at install time so that can't happen.
    """
    from sqlalchemy import select

    from backend.db.models import DonnaSchedule
    from backend.features.install import install_feature

    # Note: NO ``register_cron_handler`` call here.
    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    # Feature itself still installs; only the cron is gated.
    assert result.created is True
    assert result.feature_id
    assert result.schedule_ids == ()

    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.user_id == "u1")
            )
        ).scalars().all()
    assert rows == []


# -- Backfill --------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_backfills_untagged_observations(db) -> None:
    """Pre-feature hydration observations get tagged on fresh install."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    # Two pre-feature observations: hydration (will be tagged) + meal (won't).
    await log_observation(user_id="u1", type="hydration", fields={"glasses": 1})
    await log_observation(user_id="u1", type="meal", fields={"calories": 400})

    async with db() as session:
        before = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()
    assert all(o.feature_id is None for o in before)

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    async with db() as session:
        rows = (
            await session.execute(
                select(Observation).where(Observation.user_id == "u1")
            )
        ).scalars().all()
    by_type = {o.type: o for o in rows}
    assert by_type["hydration"].feature_id == result.feature_id
    # Meal isn't owned by hydration_tracker — must stay NULL.
    assert by_type["meal"].feature_id is None


@pytest.mark.asyncio
async def test_install_feature_no_backfill_when_no_observations(db) -> None:
    """Fresh install with zero historical observations is a clean no-op."""
    from backend.features.install import install_feature

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert result.created is True
    # Just ensuring no exception was raised when there's nothing to tag.


@pytest.mark.asyncio
async def test_install_feature_backfill_does_not_run_on_re_install(db) -> None:
    """Re-install is idempotent — observations logged BETWEEN installs are
    auto-tagged via log_observation, not the install path."""
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.features.install import install_feature
    from backend.memory.tools.log_observation import log_observation

    # Pre-existing observation, then install (backfill tags it).
    await log_observation(user_id="u1", type="hydration", fields={"glasses": 1})
    first = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert first.created is True

    # Re-install returns existing row, no second backfill pass needed.
    second = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    assert second.created is False
    assert second.feature_id == first.feature_id

    async with db() as session:
        rows = (
            await session.execute(
                select(Observation).where(
                    Observation.user_id == "u1",
                    Observation.type == "hydration",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].feature_id == first.feature_id


# -- Missing integrations ---------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_unknown_template_raises(db) -> None:
    from backend.features.install import install_feature

    with pytest.raises(ValueError, match="unknown feature template_id"):
        await install_feature(
            user_id="u1", template_id="not_a_real_template"
        )


@pytest.mark.asyncio
async def test_install_feature_blocks_when_required_integration_missing(
    db, monkeypatch
) -> None:
    """A manifest declaring required integrations must fail until connected."""
    from backend.features.manifest import FeatureManifest
    from backend.features.registry import FeatureRegistry, reset_registry_for_tests

    reset_registry_for_tests()
    registry = FeatureRegistry()
    registry.load_library()

    integration_manifest = FeatureManifest.model_validate(
        {
            "template_id": "test_inbox",
            "name": "Inbox",
            "integrations": [
                {"app": "gmail", "required": True, "watches": []}
            ],
            "observations": [
                {"type": "inbox_event", "owner": "primary"}
            ],
        }
    )
    registry.register_system_manifest(integration_manifest)

    import backend.features.registry as registry_module

    monkeypatch.setattr(registry_module, "_registry", registry)

    from backend.features.install import (
        MissingIntegrationError,
        install_feature,
    )

    with pytest.raises(MissingIntegrationError) as exc_info:
        await install_feature(user_id="u1", template_id="test_inbox")
    assert "gmail" in exc_info.value.missing


# -- Tool wrapper -----------------------------------------------------------


@pytest.mark.asyncio
async def test_install_feature_tool_wrapper_returns_ok(db) -> None:
    from backend.memory.tools.install_feature import install_feature

    result = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert result["status"] == "ok"
    payload = result["payload"]
    assert payload["status"] == "installed"
    assert payload["feature_id"]
    assert payload["template_id"] == "hydration_tracker"


@pytest.mark.asyncio
async def test_install_feature_tool_wrapper_idempotent(db) -> None:
    from backend.memory.tools.install_feature import install_feature

    first = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )
    second = await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["payload"]["status"] == "installed"
    assert second["payload"]["status"] == "already_installed"


@pytest.mark.asyncio
async def test_install_feature_tool_wrapper_unknown_template_degrades(
    db,
) -> None:
    from backend.memory.tools.install_feature import install_feature

    result = await install_feature(
        user_id="u1", template_id="not_a_template"
    )

    assert result["status"] == "degraded"
