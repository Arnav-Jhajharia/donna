"""Tests for the postgres-backed Attention store.

Uses the same in-memory aiosqlite fixture as the firing integration tests
so we exercise the real ORM mappings and async session machinery without
standing up a postgres instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID, uuid4

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


# -- Helpers ----------------------------------------------------------------


def _build_attention(*, status: str = "live", origin: str = "user_explicit"):
    from donna.attention.schema import (
        Attention,
        AttentionOrigin,
        AttentionSpec,
        AttentionStatus,
        Cadence,
        Extractor,
        Source,
        Subject,
        SurfacePolicy,
    )
    from donna.attention.vocabulary import (
        CadenceType,
        CardType,
        DomainTag,
        SourceType,
        SubjectType,
        SurfaceLevel,
    )

    spec = AttentionSpec(
        title="vitamins",
        description="take vitamins",
        card=CardType.PING,
        subject=Subject(name="self", type=SubjectType.SELF),
        domain_tags=[DomainTag.HABIT],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": "take vitamins", "expected_shape": "text"},
            )
        ],
        extractor=Extractor(prompt="echo the elicitation question back"),
        cadence=Cadence(
            type=CadenceType.SCHEDULED, params={"interval_seconds": 600}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
    )
    from uuid import NAMESPACE_URL, uuid5

    return Attention(
        id=uuid4(),
        user_id=uuid5(NAMESPACE_URL, "donna://user/u1"),
        spec=spec,
        origin=AttentionOrigin(origin),
        status=AttentionStatus(status),
        created_at=datetime.now(timezone.utc),
    )


# -- persist_attention ------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_attention_inserts_row_with_denormalized_columns(db) -> None:
    from sqlalchemy import select

    from db.models import AttentionRow
    from donna.attention.postgres_store import persist_attention

    attention = _build_attention()

    await persist_attention(attention, user_id="u1")

    async with db() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()

    assert row.user_id == "u1"
    assert row.title == "vitamins"
    assert row.card == "ping"
    assert row.cadence_type == "scheduled"
    assert row.origin == "user_explicit"
    assert row.status == "live"
    assert row.payload["spec"]["card"] == "ping"
    assert row.payload["status"] == "live"


@pytest.mark.asyncio
async def test_persist_attention_upserts_on_repeat(db) -> None:
    from sqlalchemy import func, select

    from db.models import AttentionRow
    from donna.attention.postgres_store import persist_attention
    from donna.attention.schema import AttentionStatus

    attention = _build_attention()

    await persist_attention(attention, user_id="u1")
    paused = attention.model_copy(update={"status": AttentionStatus.PAUSED})
    await persist_attention(paused, user_id="u1")

    async with db() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(AttentionRow)
            )
        ).scalar_one()
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()

    assert count == 1
    assert row.status == "paused"
    assert row.payload["status"] == "paused"


# -- update_attention_status ------------------------------------------------


@pytest.mark.asyncio
async def test_update_attention_status_returns_true_and_writes_through(db) -> None:
    from sqlalchemy import select

    from db.models import AttentionRow
    from donna.attention.postgres_store import (
        persist_attention,
        update_attention_status,
    )
    from donna.attention.schema import AttentionStatus

    attention = _build_attention()
    await persist_attention(attention, user_id="u1")

    updated = await update_attention_status(
        str(attention.id), AttentionStatus.RESOLVED
    )

    assert updated is True
    async with db() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()
    assert row.status == "resolved"
    assert row.payload["status"] == "resolved"


@pytest.mark.asyncio
async def test_update_attention_status_returns_false_for_unknown_id(db) -> None:
    from donna.attention.postgres_store import update_attention_status
    from donna.attention.schema import AttentionStatus

    result = await update_attention_status(
        str(uuid4()), AttentionStatus.RESOLVED
    )

    assert result is False


# -- record_last_surfaced ---------------------------------------------------


@pytest.mark.asyncio
async def test_record_last_surfaced_stamps_columns_and_payload(db) -> None:
    from sqlalchemy import select

    from db.models import AttentionRow
    from donna.attention.postgres_store import (
        persist_attention,
        record_last_surfaced,
    )

    attention = _build_attention()
    await persist_attention(attention, user_id="u1")

    fired_at = datetime(2026, 4, 26, 12, 0)
    ok = await record_last_surfaced(str(attention.id), at=fired_at)

    assert ok is True
    async with db() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()
    assert row.last_surfaced_at == fired_at
    assert row.payload["update_count"] == 1


@pytest.mark.asyncio
async def test_record_last_surfaced_increments_update_count(db) -> None:
    from sqlalchemy import select

    from db.models import AttentionRow
    from donna.attention.postgres_store import (
        persist_attention,
        record_last_surfaced,
    )

    attention = _build_attention()
    await persist_attention(attention, user_id="u1")
    await record_last_surfaced(str(attention.id), at=datetime(2026, 4, 26, 12, 0))
    await record_last_surfaced(str(attention.id), at=datetime(2026, 4, 26, 12, 5))

    async with db() as session:
        row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()
    assert row.payload["update_count"] == 2


# -- read paths -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_attention_round_trips_through_pydantic(db) -> None:
    from donna.attention.postgres_store import get_attention, persist_attention

    attention = _build_attention()
    await persist_attention(attention, user_id="u1")

    rehydrated = await get_attention(str(attention.id))

    assert rehydrated is not None
    assert rehydrated.id == attention.id
    assert rehydrated.spec.title == attention.spec.title
    assert rehydrated.spec.card == attention.spec.card
    assert rehydrated.spec.cadence == attention.spec.cadence


@pytest.mark.asyncio
async def test_get_attention_returns_none_for_unknown(db) -> None:
    from donna.attention.postgres_store import get_attention

    assert await get_attention(str(uuid4())) is None


@pytest.mark.asyncio
async def test_list_attentions_filters_by_status(db) -> None:
    from donna.attention.postgres_store import (
        list_attentions_by_user,
        persist_attention,
        update_attention_status,
    )
    from donna.attention.schema import AttentionStatus

    live = _build_attention()
    paused = _build_attention()
    await persist_attention(live, user_id="u1")
    await persist_attention(paused, user_id="u1")
    await update_attention_status(str(paused.id), AttentionStatus.PAUSED)

    all_attentions = await list_attentions_by_user("u1")
    only_live = await list_attentions_by_user("u1", status=AttentionStatus.LIVE)
    only_paused = await list_attentions_by_user("u1", status=AttentionStatus.PAUSED)

    assert {a.id for a in all_attentions} == {live.id, paused.id}
    assert {a.id for a in only_live} == {live.id}
    assert {a.id for a in only_paused} == {paused.id}


# -- worker bridge ---------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_records_last_surfaced_for_attention_row(db) -> None:
    """The worker's _maybe_record_attention_surface must stamp the postgres row."""
    from sqlalchemy import select

    from backend.memory.jobs.schedule_worker import _maybe_record_attention_surface
    from db.models import AttentionRow, DonnaSchedule
    from donna.attention.postgres_store import persist_attention

    attention = _build_attention()
    await persist_attention(attention, user_id="u1")

    async with db() as session:
        row = DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=datetime(2026, 4, 26, 12, 0),
            origin="user",
            context={"messages": [{"type": "text", "body": "x"}]},
            attention_id=str(attention.id),
            recurrence_meta={
                "cadence_type": "scheduled",
                "cadence_params": {"interval_seconds": 600},
                "user_tz": "UTC",
                "question": "x",
            },
            fired=True,
            fired_at=datetime(2026, 4, 26, 12, 0),
            status="done",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    await _maybe_record_attention_surface(row)

    async with db() as session:
        att_row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == str(attention.id))
            )
        ).scalar_one()
    assert att_row.last_surfaced_at == datetime(2026, 4, 26, 12, 0)


@pytest.mark.asyncio
async def test_worker_skips_attention_surface_for_legacy_rows(db) -> None:
    """Rows without attention_id (legacy schedule_reminder fires) must no-op."""
    from backend.memory.jobs.schedule_worker import _maybe_record_attention_surface
    from db.models import DonnaSchedule

    row = DonnaSchedule(
        user_id="u1",
        phone="+15551234567",
        fire_at=datetime(2026, 4, 26, 12, 0),
        origin="user",
        context={"messages": [{"type": "text", "body": "legacy"}]},
        fired=True,
        status="done",
    )

    # Should not raise even though there's no AttentionRow for this row.
    await _maybe_record_attention_surface(row)
