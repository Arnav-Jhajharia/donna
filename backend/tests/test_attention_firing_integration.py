"""End-to-end firing tier tests with an in-memory DB.

Exercises the full path from materializing a fire → worker re-enqueue →
cancel/snooze. Uses the same aiosqlite fixture pattern as the integrations
tests so the production async_session is transparently rerouted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
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


def _ping_attention(*, user_id: str, cadence_params: dict, cadence_type: str = "scheduled"):
    from datetime import datetime, timezone
    from uuid import UUID, uuid4

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
                params={"question": "take your vitamins", "expected_shape": "text"},
            )
        ],
        extractor=Extractor(prompt="echo the elicitation question back to the user"),
        cadence=Cadence(type=CadenceType(cadence_type), params=cadence_params),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
    )
    return Attention(
        id=uuid4(),
        user_id=UUID(user_id) if _looks_like_uuid(user_id) else _stable_uuid(user_id),
        spec=spec,
        origin=AttentionOrigin.USER_EXPLICIT,
        status=AttentionStatus.LIVE,
        created_at=datetime.now(timezone.utc),
    )


def _looks_like_uuid(value: str) -> bool:
    from uuid import UUID

    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def _stable_uuid(value: str):
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, f"donna://user/{value}")


# -- materialize_next_fire --------------------------------------------------


@pytest.mark.asyncio
async def test_materialize_next_fire_inserts_row_for_recurring(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import materialize_next_fire

    attention = _ping_attention(
        user_id="u1",
        cadence_params={"interval_seconds": 600},
        cadence_type="scheduled",
    )

    schedule_id = await materialize_next_fire(
        attention,
        user_id="u1",
        user_phone="+15551234567",
        user_tz="Asia/Singapore",
        after=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert schedule_id is not None
    async with db() as session:
        row = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == schedule_id)
            )
        ).scalar_one()

    assert row.attention_id == str(attention.id)
    assert row.recurrence_meta == {
        "cadence_type": "scheduled",
        "cadence_params": {"interval_seconds": 600},
        "user_tz": "Asia/Singapore",
        "question": "take your vitamins",
    }
    # 12:00 UTC + 10 min = 12:10 UTC, stored naive UTC
    assert row.fire_at == datetime(2026, 4, 26, 12, 10)
    assert row.fired is False
    assert row.status == "pending"
    assert row.context["messages"] == [
        {"type": "text", "body": "take your vitamins"}
    ]


@pytest.mark.asyncio
async def test_materialize_next_fire_returns_none_for_past_one_shot(db) -> None:
    from donna.attention.firing import materialize_next_fire

    attention = _ping_attention(
        user_id="u1",
        cadence_type="one_shot",
        cadence_params={"trigger_at": "2020-01-01T00:00:00+00:00"},
    )

    schedule_id = await materialize_next_fire(
        attention,
        user_id="u1",
        user_phone="+15551234567",
        user_tz="UTC",
    )

    assert schedule_id is None


# -- worker re-enqueue ------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_re_enqueues_next_fire_for_recurring(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import materialize_next_fire

    attention = _ping_attention(
        user_id="u1",
        cadence_params={"interval_seconds": 300},
    )

    initial_id = await materialize_next_fire(
        attention,
        user_id="u1",
        user_phone="+15551234567",
        user_tz="UTC",
        after=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
    )
    assert initial_id is not None

    # Pretend the worker just delivered the row. Mark it fired and call the
    # private helper directly to avoid bringing up WhatsApp.
    from backend.memory.jobs.schedule_worker import _maybe_enqueue_next_fire

    async with db() as session:
        delivered = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == initial_id)
            )
        ).scalar_one()

    await _maybe_enqueue_next_fire(delivered)

    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.attention_id == str(attention.id))
                .order_by(DonnaSchedule.fire_at.asc())
            )
        ).scalars().all()

    assert len(rows) == 2
    assert rows[0].id == initial_id
    # Initial fire was 12:00 + 5 min = 12:05; re-enqueue anchors on that and
    # produces 12:10.
    assert rows[0].fire_at == datetime(2026, 4, 26, 12, 5)
    next_row = rows[1]
    assert next_row.fired is False
    assert next_row.fire_at == datetime(2026, 4, 26, 12, 10)
    assert next_row.recurrence_meta == delivered.recurrence_meta


@pytest.mark.asyncio
async def test_worker_does_not_re_enqueue_for_one_shot(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import materialize_next_fire

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    attention = _ping_attention(
        user_id="u1",
        cadence_type="one_shot",
        cadence_params={"trigger_at": future.isoformat()},
    )

    initial_id = await materialize_next_fire(
        attention, user_id="u1", user_phone="+15551234567", user_tz="UTC"
    )
    assert initial_id is not None

    from backend.memory.jobs.schedule_worker import _maybe_enqueue_next_fire

    async with db() as session:
        delivered = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == initial_id)
            )
        ).scalar_one()

    await _maybe_enqueue_next_fire(delivered)

    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.attention_id == str(attention.id)
                )
            )
        ).scalars().all()

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_worker_skips_re_enqueue_for_legacy_rows_without_attention(db) -> None:
    """Old-style schedule_reminder rows have no attention_id and must remain unaffected."""
    from db.models import DonnaSchedule

    async with db() as session:
        row = DonnaSchedule(
            user_id="u1",
            phone="+15551234567",
            fire_at=datetime(2026, 4, 26, 12, 0),
            origin="user",
            context={"messages": [{"type": "text", "body": "legacy"}]},
            fired=True,
            status="done",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    from backend.memory.jobs.schedule_worker import _maybe_enqueue_next_fire

    await _maybe_enqueue_next_fire(row)

    async with db() as session:
        rows = (
            await session.execute(select(DonnaSchedule))
        ).scalars().all()

    assert len(rows) == 1


# -- cancel / snooze --------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_pending_fires_removes_unfired_rows(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import cancel_pending_fires, materialize_next_fire

    attention = _ping_attention(
        user_id="u1",
        cadence_params={"interval_seconds": 600},
    )
    await materialize_next_fire(
        attention, user_id="u1", user_phone="+15551234567", user_tz="UTC"
    )

    deleted = await cancel_pending_fires(str(attention.id))

    assert deleted == 1
    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.attention_id == str(attention.id)
                )
            )
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_cancel_pending_fires_does_not_touch_fired_rows(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import cancel_pending_fires, materialize_next_fire

    attention = _ping_attention(
        user_id="u1",
        cadence_params={"interval_seconds": 600},
    )
    schedule_id = await materialize_next_fire(
        attention, user_id="u1", user_phone="+15551234567", user_tz="UTC"
    )
    async with db() as session:
        row = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == schedule_id)
            )
        ).scalar_one()
        row.fired = True
        row.status = "done"
        await session.commit()

    deleted = await cancel_pending_fires(str(attention.id))

    assert deleted == 0
    async with db() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.attention_id == str(attention.id)
                )
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_snooze_pending_fires_pushes_fire_at_forward(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import materialize_next_fire, snooze_pending_fires

    attention = _ping_attention(
        user_id="u1",
        cadence_params={"interval_seconds": 600},
    )
    await materialize_next_fire(
        attention,
        user_id="u1",
        user_phone="+15551234567",
        user_tz="UTC",
        after=datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
    )

    new_fire_at = await snooze_pending_fires(str(attention.id), by_seconds=600)

    assert new_fire_at == datetime(2026, 4, 26, 12, 20)
    async with db() as session:
        row = (
            await session.execute(
                select(DonnaSchedule).where(
                    DonnaSchedule.attention_id == str(attention.id)
                )
            )
        ).scalar_one()
    assert row.fire_at == datetime(2026, 4, 26, 12, 20)


@pytest.mark.asyncio
async def test_snooze_pending_fires_returns_none_when_nothing_pending(db) -> None:
    from donna.attention.firing import snooze_pending_fires

    result = await snooze_pending_fires(str(_stable_uuid("nope")), by_seconds=60)

    assert result is None


# -- list_pending_for_user --------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_for_user_returns_only_unfired_attention_rows(db) -> None:
    from db.models import DonnaSchedule
    from donna.attention.firing import list_pending_for_user, materialize_next_fire

    pending = _ping_attention(user_id="u1", cadence_params={"interval_seconds": 600})
    fired = _ping_attention(user_id="u1", cadence_params={"interval_seconds": 600})

    await materialize_next_fire(
        pending, user_id="u1", user_phone="+15551234567", user_tz="UTC"
    )
    fired_id = await materialize_next_fire(
        fired, user_id="u1", user_phone="+15551234567", user_tz="UTC"
    )
    async with db() as session:
        row = (
            await session.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == fired_id)
            )
        ).scalar_one()
        row.fired = True
        await session.commit()

    # A legacy non-attention row must also be excluded.
    async with db() as session:
        session.add(
            DonnaSchedule(
                user_id="u1",
                phone="+15551234567",
                fire_at=datetime(2026, 4, 26, 9, 0),
                origin="user",
                context={"messages": [{"type": "text", "body": "legacy"}]},
                fired=False,
                status="pending",
            )
        )
        await session.commit()

    rows = await list_pending_for_user("u1")

    assert len(rows) == 1
    assert rows[0]["attention_id"] == str(pending.id)
    assert rows[0]["message"] == "take your vitamins"
