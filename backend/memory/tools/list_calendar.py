"""list_calendar — upcoming events."""
from __future__ import annotations

from datetime import timedelta

from backend.memory.time import format_local, timezone_label, utcnow_naive
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List upcoming calendar entries for this user. "
    "Use when deciding what's coming up ('meetings today?', 'anything tomorrow?')."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "within_days": {"type": "integer", "default": 7},
        "limit": {"type": "integer", "default": 20},
    },
    "required": [],
}


@instrument_memory_op("postgres.calendar")
async def list_calendar(
    user_id: str, within_days: int = 7, limit: int = 20
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import CalendarEntry, User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    now = utcnow_naive()
    until = now + timedelta(days=within_days)
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            stmt = (
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.start_time >= now)
                .where(CalendarEntry.start_time <= until)
                .order_by(CalendarEntry.start_time.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return degraded("db error")
    if not rows:
        return no_hits()
    return ok(
        [
            {
                "id": r.id,
                "title": r.title,
                "start_time": r.start_time.isoformat() if r.start_time else None,
                "end_time": r.end_time.isoformat() if r.end_time else None,
                "start_time_local": format_local(r.start_time, timezone_name),
                "end_time_local": format_local(r.end_time, timezone_name),
                "timezone": timezone_label(timezone_name),
                "location": r.location,
            }
            for r in rows
        ]
    )
