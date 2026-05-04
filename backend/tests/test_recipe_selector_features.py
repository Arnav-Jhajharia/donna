"""Recipe selector reads active features into ``have_caps``.

Without this, a user who installs hydration via ``install_feature`` would
still see ``hydration_silent_pings`` offered in the recipe mosaic — the
selector previously only looked at attentions and missed feature-derived
capabilities.
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


@pytest.mark.asyncio
async def test_active_feature_blocks_its_recipe(db) -> None:
    """Hydration installed → ``hydration_silent_pings`` recipe is filtered."""
    from backend.dashboard.recipe_selector import select_for_day_one
    from backend.features.install import install_feature

    # Sanity: before install, the hydration recipe is offered.
    before = await select_for_day_one("u1", k=20)
    before_ids = {r.id for r in before}
    assert "hydration_silent_pings" in before_ids

    await install_feature(
        user_id="u1", template_id="hydration_tracker"
    )

    after = await select_for_day_one("u1", k=20)
    after_ids = {r.id for r in after}
    assert "hydration_silent_pings" not in after_ids


@pytest.mark.asyncio
async def test_paused_feature_unblocks_its_recipe(db) -> None:
    """Paused features don't claim capabilities — the recipe is offerable
    again so the user can re-engage via the mosaic.
    """
    from backend.dashboard.recipe_selector import select_for_day_one
    from backend.features.install import install_feature
    from backend.features.lifecycle import pause_feature

    await install_feature(user_id="u1", template_id="hydration_tracker")
    await pause_feature(user_id="u1", template_id="hydration_tracker")

    rows = await select_for_day_one("u1", k=20)
    ids = {r.id for r in rows}
    assert "hydration_silent_pings" in ids


@pytest.mark.asyncio
async def test_archived_feature_unblocks_its_recipe(db) -> None:
    """Archived features also surface the recipe again."""
    from backend.dashboard.recipe_selector import select_for_day_one
    from backend.features.install import install_feature
    from backend.features.lifecycle import archive_feature

    await install_feature(user_id="u1", template_id="hydration_tracker")
    await archive_feature(user_id="u1", template_id="hydration_tracker")

    rows = await select_for_day_one("u1", k=20)
    ids = {r.id for r in rows}
    assert "hydration_silent_pings" in ids


@pytest.mark.asyncio
async def test_no_feature_no_change(db) -> None:
    """Without features, the selector behaves exactly as before."""
    from backend.dashboard.recipe_selector import select_for_day_one

    rows = await select_for_day_one("u1", k=20)
    assert rows
    assert any(r.id == "hydration_silent_pings" for r in rows)
