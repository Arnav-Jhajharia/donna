"""read_situation_brief — return the stored temporal mental model."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Read Donna's stored temporal situation brief for the user. This is the compact "
    "last-week / this-week / next-week mental model saved in users.living_profile."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}


@instrument_memory_op("living_profile")
async def read_situation_brief(user_id: str) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    try:
        async with async_session() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    except Exception:
        return degraded("db error")

    if user is None or not user.living_profile:
        return no_hits()
    brief = dict(user.living_profile or {}).get("situation_brief")
    if not isinstance(brief, dict):
        return no_hits()
    return ok(brief)
