"""list_observations — countable events (meals, mood, sleep, etc.)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok

DESCRIPTION = (
    "List countable events the user has logged (meals, expenses, mood, sleep, exercise). "
    "Use for 'how much did I spend this week?' or 'what did I eat today?'."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "since_days": {"type": "integer", "default": 7},
        "limit": {"type": "integer", "default": 50},
    },
    "required": [],
}


async def list_observations(
    user_id: str,
    type: str | None = None,
    since_days: int = 7,
    limit: int = 50,
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import Observation
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=since_days)
    try:
        async with async_session() as session:
            stmt = (
                select(Observation)
                .where(Observation.user_id == user_id)
                .where(Observation.event_time >= since)
                .order_by(Observation.event_time.desc())
                .limit(limit)
            )
            if type:
                stmt = stmt.where(Observation.type == type)
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return degraded("db error")

    if not rows:
        return no_hits()
    return ok(
        [
            {
                "id": r.id,
                "type": r.type,
                "event_time": r.event_time.isoformat() if r.event_time else None,
                "tags": r.tags,
                "fields": r.fields,
                "confidence": r.confidence,
            }
            for r in rows
        ]
    )
