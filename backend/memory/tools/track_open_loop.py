"""track_open_loop — capture an unresolved thread."""
from __future__ import annotations

import logging

from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Record an unresolved thread (something the user said they'd follow up on, "
    "a decision left hanging, a commitment made). Use when detection seems warranted."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "source_message": {"type": "string"},
    },
    "required": ["content"],
}


@instrument_memory_op("postgres.open_loops")
async def track_open_loop(
    user_id: str, content: str, source_message: str | None = None
) -> ToolResult:
    try:
        from backend.db.models import OpenLoop
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            loop = OpenLoop(user_id=user_id, content=content, source_message=source_message)
            session.add(loop)
            await session.commit()
            await session.refresh(loop)
            refreshed = await _refresh_situation_brief(user_id)
            return ok({"id": loop.id, "situation_brief_refreshed": refreshed})
    except Exception:
        return degraded("db error")


async def _refresh_situation_brief(user_id: str) -> bool:
    try:
        from backend.memory.tools.refresh_situation_brief import refresh_situation_brief_best_effort

        return await refresh_situation_brief_best_effort(user_id)
    except Exception:
        logger.exception("track_open_loop: situation brief refresh failed")
        return False
