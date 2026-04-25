"""Shared fixtures for integrations tests.

Provides an in-memory aiosqlite session that monkey-patches
`backend.db.session.async_session` (and the root `db.session.async_session`)
so production code paths transparently target the test database.

JSONB columns fall back to JSON on SQLite via the compile shim.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


@pytest_asyncio.fixture
async def db(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh in-memory DB with a seeded user; production async_session is
    monkey-patched to the test sessionmaker for the duration of the test."""
    from db.models import Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session() as s:
        s.add(User(id="u1", phone="+1"))
        s.add(User(id="u2", phone="+2"))
        await s.commit()

    import backend.db.session as backend_session
    import db.session as root_session

    monkeypatch.setattr(root_session, "async_session", test_session)
    monkeypatch.setattr(backend_session, "async_session", test_session)

    try:
        yield test_session
    finally:
        await engine.dispose()
