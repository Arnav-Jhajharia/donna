from __future__ import annotations

from datetime import datetime
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

    try:
        yield test_session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_state_snapshot_attentions_include_postgres_current_state(db) -> None:
    from backend.dashboard.state_snapshot import _fetch_attentions
    from db.models import AttentionRow

    current_state = {
        "day": "2026-05-04",
        "value": 920,
        "value_numeric": 920,
        "target": 1800,
        "progress": 0.51,
        "evidence_ids": ["obs_1"],
    }
    async with db() as session:
        session.add(
            AttentionRow(
                id="att_1",
                user_id="u1",
                title="calories",
                card="tally",
                cadence_type="on_event",
                origin="user_explicit",
                status="live",
                payload={
                    "id": "att_1",
                    "status": "live",
                    "origin": "user_explicit",
                    "spec": {
                        "title": "calories",
                        "description": "track meal calories",
                        "card": "tally",
                        "subject": {"name": "meal calories", "type": "self"},
                        "domain_tags": ["health"],
                        "cadence": {"type": "on_event", "params": {}},
                    },
                    "current_state": current_state,
                    "last_update_at": "2026-05-04T09:30:00+00:00",
                    "update_count": 3,
                },
                created_at=datetime(2026, 5, 4, 9, 0),
            )
        )
        await session.commit()

    rows = await _fetch_attentions("u1")

    assert len(rows) == 1
    assert rows[0]["id"] == "att_1"
    assert rows[0]["current_state"] == current_state
    assert rows[0]["last_update_at"] == "2026-05-04T09:30:00+00:00"


@pytest.mark.asyncio
async def test_dashboard_composer_live_attentions_use_postgres_current_state(db) -> None:
    from backend.dashboard.compose import _format_live_attention, _read_live_attentions
    from db.models import AttentionRow

    async with db() as session:
        session.add(
            AttentionRow(
                id="att_live",
                user_id="u1",
                title="calories",
                card="tally",
                cadence_type="on_event",
                origin="user_explicit",
                status="live",
                payload={
                    "spec": {
                        "title": "calories",
                        "description": "track meal calories",
                        "card": "tally",
                        "subject": {"name": "meal calories", "type": "self"},
                        "domain_tags": ["health"],
                        "cadence": {"type": "on_event", "params": {}},
                    },
                    "current_state": {
                        "rollup": "today",
                        "value": 920,
                        "target": 1800,
                        "count": 2,
                        "last_event_at": "2026-05-04T09:30:00+00:00",
                    },
                    "last_update_at": "2026-05-04T09:30:00+00:00",
                },
                created_at=datetime(2026, 5, 4, 9, 0),
            )
        )
        await session.commit()

    rows = await _read_live_attentions("u1")
    rendered = _format_live_attention(rows[0])

    assert len(rows) == 1
    assert "state: today: value=920 of 1800 (2 entries) last 09:30" in rendered
