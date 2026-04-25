"""Upsert/delete CalendarEntry rows from Composio Google Calendar payloads.

Idempotent: re-ingesting the same google_event_id refreshes mutable fields
(title, times, location) so downstream readers always see the latest version.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from db.models import CalendarEntry

logger = logging.getLogger(__name__)


def _session_factory():
    from backend.db.session import async_session

    return async_session


def _parse_dt(spec: dict | None) -> datetime | None:
    """Parse Google Calendar start/end spec. Returns naive UTC datetime."""
    if not spec:
        return None
    raw = spec.get("dateTime") or spec.get("date")
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def ingest_calendar_event(user_id: str, event: dict[str, Any]) -> None:
    google_event_id = event.get("id")
    if not google_event_id:
        return

    title = event.get("summary") or "(no title)"
    start_time = _parse_dt(event.get("start"))
    end_time = _parse_dt(event.get("end"))
    location = event.get("location")

    if start_time is None:
        return

    async with _session_factory()() as session:
        existing = (
            await session.execute(
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.google_event_id == google_event_id)
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                CalendarEntry(
                    user_id=user_id,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    google_event_id=google_event_id,
                )
            )
        else:
            existing.title = title
            existing.start_time = start_time
            existing.end_time = end_time
            existing.location = location

        await session.commit()


async def delete_calendar_event(user_id: str, google_event_id: str) -> None:
    async with _session_factory()() as session:
        await session.execute(
            delete(CalendarEntry)
            .where(CalendarEntry.user_id == user_id)
            .where(CalendarEntry.google_event_id == google_event_id)
        )
        await session.commit()
