"""Pending-notes lifecycle: insert, supersede, expiry, clear, render block."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from proactive.dispatcher import (
    clear_pending_note,
    insert_pending_note,
)
from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


def _event(topic_key="thread-A"):
    return ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="m1",
        topic_key=topic_key,
        payload={},
        signals={},
    )


def _judge(draft="hold this for next touch"):
    return JudgeResult(
        action="hold",
        register=None,
        draft=draft,
        tie_in=("antler",),
        needs_tools=False,
        reasoning="useful, not urgent",
        raw_response="{}",
    )


@pytest.mark.asyncio
async def test_insert_pending_note_writes_row(db):
    from sqlalchemy import select

    from db.models import PendingProactiveNote

    note_id = await insert_pending_note(_event(), _judge())
    assert note_id is not None

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert len(rows) == 1
    assert rows[0].draft == "hold this for next touch"
    assert rows[0].tie_in == ["antler"]
    assert rows[0].status == "pending"


@pytest.mark.asyncio
async def test_insert_supersedes_prior_pending_on_same_topic(db):
    from sqlalchemy import select

    from db.models import PendingProactiveNote

    await insert_pending_note(_event(), _judge(draft="first"))
    await insert_pending_note(_event(), _judge(draft="second"))

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    statuses = {r.status for r in rows}
    assert statuses == {"pending", "superseded"}
    pending = next(r for r in rows if r.status == "pending")
    assert pending.draft == "second"


@pytest.mark.asyncio
async def test_insert_does_not_supersede_other_topics(db):
    from sqlalchemy import select

    from db.models import PendingProactiveNote

    await insert_pending_note(_event("thread-A"), _judge(draft="A"))
    await insert_pending_note(_event("thread-B"), _judge(draft="B"))

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert len(rows) == 2
    assert all(r.status == "pending" for r in rows)


@pytest.mark.asyncio
async def test_clear_pending_note_marks_delivered(db):
    note_id = await insert_pending_note(_event(), _judge())
    cleared = await clear_pending_note(note_id, reason="delivered")
    assert cleared is True

    from sqlalchemy import select

    from db.models import PendingProactiveNote

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert rows[0].status == "delivered"
    assert rows[0].delivered_at is not None


@pytest.mark.asyncio
async def test_clear_pending_note_invalid_reason_defaults_delivered(db):
    note_id = await insert_pending_note(_event(), _judge())
    cleared = await clear_pending_note(note_id, reason="banana")
    assert cleared is True

    from sqlalchemy import select

    from db.models import PendingProactiveNote

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert rows[0].status == "delivered"


@pytest.mark.asyncio
async def test_clear_pending_note_unknown_id_returns_false(db):
    cleared = await clear_pending_note("nonexistent", reason="delivered")
    assert cleared is False


@pytest.mark.asyncio
async def test_load_pending_notes_excludes_expired(db):
    from sqlalchemy import select, update

    from db.models import PendingProactiveNote
    from donna_runtime.context_builder import load_pending_notes

    note_id = await insert_pending_note(_event(), _judge())
    # Force expiry into the past.
    async with db() as s:
        await s.execute(
            update(PendingProactiveNote)
            .where(PendingProactiveNote.id == note_id)
            .values(expires_at=datetime(2020, 1, 1))
        )
        await s.commit()

    rows = await load_pending_notes("u1")
    assert rows == []


@pytest.mark.asyncio
async def test_load_pending_notes_only_returns_pending(db):
    await insert_pending_note(_event(), _judge(draft="active"))

    # Manually insert a delivered row to make sure it gets filtered.
    from db.models import PendingProactiveNote

    async with db() as s:
        s.add(
            PendingProactiveNote(
                user_id="u1",
                source="email",
                source_ref="m_old",
                topic_key="thread-old",
                draft="already delivered",
                tie_in=[],
                reasoning="",
                status="delivered",
                created_at=datetime(2026, 4, 25),
                expires_at=datetime(2030, 1, 1),
            )
        )
        await s.commit()

    from donna_runtime.context_builder import load_pending_notes

    rows = await load_pending_notes("u1")
    assert len(rows) == 1
    assert rows[0].draft == "active"


def test_render_pending_notes_block_empty():
    from donna_runtime.context_builder import render_pending_notes_block

    assert render_pending_notes_block([]) == ""


@pytest.mark.asyncio
async def test_render_pending_notes_block_includes_metadata(db):
    from donna_runtime.context_builder import (
        load_pending_notes,
        render_pending_notes_block,
    )

    await insert_pending_note(_event(), _judge(draft="luca wants thursday"))
    rows = await load_pending_notes("u1")
    block = render_pending_notes_block(rows)
    assert "## PENDING NOTES" in block
    assert "luca wants thursday" in block
    assert "tie_in: [antler]" in block
