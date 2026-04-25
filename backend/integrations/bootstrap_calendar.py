"""Calendar bootstrap — last 30d + next 90d into calendar_entries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.integrations.calendar_ingest import ingest_calendar_event
from backend.integrations.composio_client import ComposioClient
from config import settings


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


async def bootstrap_calendar(user_id: str) -> int:
    """Backfill calendar entries spanning the last 30d through the next 90d."""
    client = _client()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    time_min = now - timedelta(days=30)
    time_max = now + timedelta(days=90)
    events = await client.list_calendar_events(
        user_id=user_id, time_min=time_min, time_max=time_max
    )
    count = 0
    for event in events:
        await ingest_calendar_event(user_id, event)
        count += 1
    return count
