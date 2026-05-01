"""list_open_loops — unresolved threads."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List unresolved threads (open loops) for this user — what's still owed or pending. "
    "Use when deciding whether to resurface a prior topic."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["active", "closed", "all"], "default": "active"},
        "limit": {"type": "integer", "default": 20},
    },
    "required": [],
}


@instrument_memory_op("postgres.open_loops")
async def list_open_loops(
    user_id: str, status: str = "active", limit: int = 20
) -> ToolResult:
    try:
        from backend.db.session import async_session
        from backend.memory.tools._open_loop_view import read_open_loops_unified
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            statuses = None if status == "all" else (status,)
            views = await read_open_loops_unified(
                session,
                user_id=user_id,
                statuses=statuses,
                limit=limit,
            )
    except Exception:
        return degraded("db error")
    if not views:
        return no_hits()
    return ok(
        [
            {
                "id": v.id,
                "content": v.content,
                "status": v.status,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in views
        ]
    )
