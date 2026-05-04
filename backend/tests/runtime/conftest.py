from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from donna_runtime.env import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # runtime/ → tests/ → backend/ → root
load_dotenv(_ROOT / ".env")


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@pytest_asyncio.fixture
async def db(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Mirror of backend/tests/proactive/conftest.py db fixture.

    In-memory SQLite, JSONB→JSON via the compile shim, seeds u1/u2,
    and monkeypatches both root and backend session modules so
    production code paths target the test DB.
    """
    from db.models import Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session() as s:
        s.add(User(id="u1", phone="+1", timezone="Asia/Singapore"))
        s.add(User(id="u2", phone="+2", timezone="Asia/Singapore"))
        await s.commit()

    import backend.db.session as backend_session
    import db.session as root_session

    monkeypatch.setattr(root_session, "async_session", test_session)
    monkeypatch.setattr(backend_session, "async_session", test_session)

    try:
        yield test_session
    finally:
        await engine.dispose()
