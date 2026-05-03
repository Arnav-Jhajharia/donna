"""Tests for the post-turn dashboard refresh hook."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@pytest_asyncio.fixture
async def db(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh in-memory DB seeded with one user + a stale manifest."""
    from db.models import Base, DashboardManifest, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session() as s:
        s.add(User(id="u1", phone="+1"))
        s.add(
            DashboardManifest(
                user_id="u1",
                plan_jsonb={"thesis": "old"},
                generated_at=datetime.utcnow() - timedelta(hours=2),
                trigger="seeded",
            )
        )
        await s.commit()

    import backend.db.session as backend_session
    import db.session as root_session

    monkeypatch.setattr(root_session, "async_session", test_session)
    monkeypatch.setattr(backend_session, "async_session", test_session)

    try:
        yield test_session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_user_id_is_noop(db, monkeypatch) -> None:
    from backend.memory.hooks import refresh_dashboard

    called: list[str] = []

    async def _stub_compose(*, user_id, trigger):
        called.append(user_id)
        return {"thesis": "fresh"}

    monkeypatch.setattr(
        "backend.dashboard.compose.compose_manifest", _stub_compose
    )
    await refresh_dashboard.run({})
    await asyncio.sleep(0.05)
    assert called == []


@pytest.mark.asyncio
async def test_stale_manifest_triggers_recompose(db, monkeypatch) -> None:
    from backend.memory.hooks import refresh_dashboard

    composed: list[tuple[str, str]] = []
    upserted: list[str] = []

    async def _stub_compose(*, user_id, trigger):
        composed.append((user_id, trigger))
        return {"thesis": "fresh"}

    async def _stub_upsert(user_id, plan, trigger="post_turn"):
        upserted.append(user_id)

    monkeypatch.setattr(
        "backend.dashboard.compose.compose_manifest", _stub_compose
    )
    monkeypatch.setattr(
        "backend.dashboard.store.upsert_manifest", _stub_upsert
    )

    await refresh_dashboard.run({"user_id": "u1"})
    # Yield so the spawned task runs.
    for _ in range(20):
        if composed and upserted:
            break
        await asyncio.sleep(0.01)

    assert composed == [("u1", "post_turn")]
    assert upserted == ["u1"]


@pytest.mark.asyncio
async def test_fresh_manifest_skips_recompose(db, monkeypatch) -> None:
    """Within debounce window, no work happens."""
    from db.models import DashboardManifest
    from sqlalchemy import update

    # Mark the seeded manifest as 1 minute old — well within the default
    # 600s debounce.
    async with db() as s:
        await s.execute(
            update(DashboardManifest)
            .where(DashboardManifest.user_id == "u1")
            .values(generated_at=datetime.utcnow() - timedelta(seconds=60))
        )
        await s.commit()

    from backend.memory.hooks import refresh_dashboard

    called: list[str] = []

    async def _stub_compose(*, user_id, trigger):
        called.append(user_id)
        return {"thesis": "fresh"}

    monkeypatch.setattr(
        "backend.dashboard.compose.compose_manifest", _stub_compose
    )

    await refresh_dashboard.run({"user_id": "u1"})
    await asyncio.sleep(0.05)
    assert called == []


@pytest.mark.asyncio
async def test_no_manifest_yet_triggers_recompose(db, monkeypatch) -> None:
    """First-ever turn for a user with no manifest should still recompose."""
    from db.models import DashboardManifest
    from sqlalchemy import delete

    async with db() as s:
        await s.execute(delete(DashboardManifest))
        await s.commit()

    from backend.memory.hooks import refresh_dashboard

    composed: list[tuple[str, str]] = []

    async def _stub_compose(*, user_id, trigger):
        composed.append((user_id, trigger))
        return {"thesis": "fresh"}

    async def _stub_upsert(user_id, plan, trigger="post_turn"):
        pass

    monkeypatch.setattr(
        "backend.dashboard.compose.compose_manifest", _stub_compose
    )
    monkeypatch.setattr(
        "backend.dashboard.store.upsert_manifest", _stub_upsert
    )

    await refresh_dashboard.run({"user_id": "u1"})
    for _ in range(20):
        if composed:
            break
        await asyncio.sleep(0.01)
    assert composed == [("u1", "post_turn")]


@pytest.mark.asyncio
async def test_min_age_env_var_is_respected(db, monkeypatch) -> None:
    """Setting DONNA_DASHBOARD_REFRESH_MIN_AGE_S to 60s lets a 90s-old
    manifest trigger a refresh."""
    from db.models import DashboardManifest
    from sqlalchemy import update

    async with db() as s:
        await s.execute(
            update(DashboardManifest)
            .where(DashboardManifest.user_id == "u1")
            .values(generated_at=datetime.utcnow() - timedelta(seconds=90))
        )
        await s.commit()

    monkeypatch.setenv("DONNA_DASHBOARD_REFRESH_MIN_AGE_S", "60")

    from backend.memory.hooks import refresh_dashboard

    composed: list[str] = []

    async def _stub_compose(*, user_id, trigger):
        composed.append(user_id)
        return {"thesis": "fresh"}

    async def _stub_upsert(user_id, plan, trigger="post_turn"):
        pass

    monkeypatch.setattr(
        "backend.dashboard.compose.compose_manifest", _stub_compose
    )
    monkeypatch.setattr(
        "backend.dashboard.store.upsert_manifest", _stub_upsert
    )

    await refresh_dashboard.run({"user_id": "u1"})
    for _ in range(20):
        if composed:
            break
        await asyncio.sleep(0.01)
    assert composed == ["u1"]
