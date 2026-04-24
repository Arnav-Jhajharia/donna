"""list_observations — countable events (meals, mood, sleep, etc.)."""
from __future__ import annotations

from datetime import timedelta

from backend.memory.time import format_local, period_bounds, timezone_label, utcnow_naive
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List countable events the user has logged (meals, expenses, mood, sleep, exercise). "
    "Use for 'how much did I spend this week?' or 'what did I eat today?'."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "period": {
            "type": "string",
            "description": "Optional local-time period: today, yesterday, this_week, or last_week.",
        },
        "since_days": {"type": "integer", "default": 7},
        "limit": {"type": "integer", "default": 50},
    },
    "required": [],
}


@instrument_memory_op("postgres.observations")
async def list_observations(
    user_id: str,
    type: str | None = None,
    period: str | None = None,
    since_days: int = 7,
    limit: int = 50,
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import Observation, User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            bounds = period_bounds(period, timezone_name)
            if bounds:
                since, until = bounds
            else:
                since = utcnow_naive() - timedelta(days=max(0, int(since_days)))
                until = None
            stmt = (
                select(Observation)
                .where(Observation.user_id == user_id)
                .where(Observation.event_time >= since)
                .order_by(Observation.event_time.desc())
                .limit(limit)
            )
            if until is not None:
                stmt = stmt.where(Observation.event_time < until)
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
                "event_time_local": format_local(r.event_time, timezone_name),
                "timezone": timezone_label(timezone_name),
                "tags": r.tags,
                "fields": r.fields,
                "confidence": r.confidence,
            }
            for r in rows
        ]
    )
