from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import CalendarEntry


@pytest.fixture
def fake_client(monkeypatch):
    events = [
        {
            "id": f"e{i}",
            "summary": f"event {i}",
            "start": {
                "dateTime": (
                    datetime.now(timezone.utc) + timedelta(days=i)
                ).isoformat()
            },
            "end": {
                "dateTime": (
                    datetime.now(timezone.utc) + timedelta(days=i, hours=1)
                ).isoformat()
            },
        }
        for i in range(5)
    ]

    class Fake:
        async def list_calendar_events(
            self, user_id, time_min, time_max, max_results=250
        ):
            return events

    monkeypatch.setattr(
        "backend.integrations.bootstrap_calendar._client",
        lambda: Fake(),
    )
    return events


@pytest.mark.asyncio
async def test_bootstrap_calendar_ingests_events(db, fake_client):
    from backend.integrations.bootstrap_calendar import bootstrap_calendar

    n = await bootstrap_calendar("u1")
    assert n == 5

    async with db() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 5
