"""recall_chat_thread — fetch recent chat messages beyond the last 5."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Load recent chat history for this user beyond the 5 messages already in context. "
    "Use when you need to trace what was said 10-50 messages back."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "default": 30},
        "before_id": {"type": "string"},
    },
    "required": [],
}


@instrument_memory_op("postgres.chat_messages")
async def recall_chat_thread(
    user_id: str, limit: int = 30, before_id: str | None = None
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import ChatMessage
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    try:
        async with async_session() as session:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
            if before_id:
                sub = select(ChatMessage.created_at).where(ChatMessage.id == before_id)
                stmt = stmt.where(ChatMessage.created_at < sub.scalar_subquery())
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return degraded("db error")

    if not rows:
        return no_hits()
    return ok(
        [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reversed(rows)
        ]
    )
