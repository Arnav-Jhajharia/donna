"""Schema-level smoke for Integration + EmailMessage models.

Uses in-memory aiosqlite. JSONB columns fall back to JSON on SQLite, so
model binding still works for these tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


from db.models import Base, EmailMessage, Integration, ProactivePing, User  # noqa: E402


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        s.add(User(id="u1", phone="+1"))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_integration_model_defaults(session: AsyncSession) -> None:
    session.add(Integration(user_id="u1", provider="google", product="calendar"))
    await session.commit()

    row = (await session.execute(select(Integration))).scalar_one()
    assert row.status == "pending"
    assert row.composio_connection_id is None
    assert row.connected_at is None


@pytest.mark.asyncio
async def test_email_message_model_defaults(session: AsyncSession) -> None:
    session.add(
        EmailMessage(
            user_id="u1",
            gmail_message_id="m1",
            thread_id="t1",
            from_address="a@b.com",
            subject="hi",
            ingest_depth="full",
            internal_date=datetime(2026, 4, 25, tzinfo=timezone.utc).replace(tzinfo=None),
        )
    )
    await session.commit()

    msg = (await session.execute(select(EmailMessage))).scalar_one()
    assert msg.body_stored is False
    assert msg.is_important is False
    assert msg.labels == []


@pytest.mark.asyncio
async def test_proactive_ping_model_defaults(session: AsyncSession) -> None:
    session.add(ProactivePing(user_id="u1", source="email", message_ref="m1"))
    await session.commit()

    ping = (await session.execute(select(ProactivePing))).scalar_one()
    assert ping.source == "email"
    assert ping.message_ref == "m1"
    assert ping.suppressed_reason is None
    assert ping.fired_at is not None
