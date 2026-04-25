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
        from sqlalchemy import select

        from backend.db.models import OpenLoop
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            stmt = (
                select(OpenLoop)
                .where(OpenLoop.user_id == user_id)
                .order_by(OpenLoop.created_at.desc())
                .limit(limit)
            )
            if status != "all":
                stmt = stmt.where(OpenLoop.status == status)
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return degraded("db error")
    if not rows:
        return no_hits()
    return ok(
        [
            {
                "id": r.id,
                "content": r.content,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    )
