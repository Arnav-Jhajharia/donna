"""close_open_loop — mark a tracked loop resolved."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Mark a prior open loop as resolved. Pass the loop id from list_open_loops. "
    "Use when the user's latest message resolves a pending thread."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"loop_id": {"type": "string"}},
    "required": ["loop_id"],
}


@instrument_memory_op("postgres.open_loops")
async def close_open_loop(user_id: str, loop_id: str) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import OpenLoop
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            result = await session.execute(
                select(OpenLoop).where(OpenLoop.id == loop_id, OpenLoop.user_id == user_id)
            )
            loop = result.scalar_one_or_none()
            if loop is None:
                return no_hits()
            loop.status = "closed"
            loop.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
            refreshed = await _refresh_situation_brief(user_id)
            return ok({"id": loop_id, "status": "closed", "situation_brief_refreshed": refreshed})
    except Exception:
        return degraded("db error")


async def _refresh_situation_brief(user_id: str) -> bool:
    try:
        from backend.memory.tools.refresh_situation_brief import refresh_situation_brief_best_effort

        return await refresh_situation_brief_best_effort(user_id)
    except Exception:
        logger.exception("close_open_loop: situation brief refresh failed")
        return False
