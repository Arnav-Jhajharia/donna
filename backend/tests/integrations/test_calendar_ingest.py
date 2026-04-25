from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.integrations.calendar_ingest import (
    delete_calendar_event,
    ingest_calendar_event,
)
from db.models import CalendarEntry


def _event(event_id: str = "e1", summary: str = "standup") -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": "2026-04-25T09:00:00Z"},
        "end": {"dateTime": "2026-04-25T09:30:00Z"},
        "location": "zoom",
    }


@pytest.mark.asyncio
async def test_ingest_calendar_event_creates(db) -> None:
    await ingest_calendar_event("u1", _event())
    async with db() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.title == "standup"
    assert row.google_event_id == "e1"
    assert row.location == "zoom"


@pytest.mark.asyncio
async def test_ingest_calendar_event_updates(db) -> None:
    await ingest_calendar_event("u1", _event(summary="standup"))
    await ingest_calendar_event("u1", _event(summary="retro"))
    async with db() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "retro"


@pytest.mark.asyncio
async def test_delete_calendar_event_removes(db) -> None:
    await ingest_calendar_event("u1", _event())
    await delete_calendar_event("u1", "e1")
    async with db() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_calendar_event_skips_when_start_missing(db) -> None:
    bad = {"id": "e2", "summary": "no time"}
    await ingest_calendar_event("u1", bad)
    async with db() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_calendar_event_falls_back_to_no_title(db) -> None:
    event = _event()
    event.pop("summary")
    await ingest_calendar_event("u1", event)
    async with db() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.title == "(no title)"


@pytest.mark.asyncio
async def test_ingest_all_day_event_uses_date_field(db) -> None:
    event = {
        "id": "e3",
        "summary": "holiday",
        "start": {"date": "2026-04-25"},
        "end": {"date": "2026-04-26"},
    }
    await ingest_calendar_event("u1", event)
    async with db() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.start_time is not None
