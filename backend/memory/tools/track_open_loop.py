"""track_open_loop — capture an unresolved thread."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, ok

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
            return ok({"id": loop.id})
    except Exception:
        return degraded("db error")
