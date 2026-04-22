"""log_observation — record a countable event."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, ok

DESCRIPTION = (
    "Log a countable/measurable user event (meal, expense, mood, habit, sleep, etc.). "
    "Model decides when something the user said is worth tracking as structured data."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "fields": {"type": "object"},
        "tags": {"type": "object"},
        "raw": {"type": "string"},
        "confidence": {"type": "number", "default": 1.0},
    },
    "required": ["type", "fields"],
}


async def log_observation(
    user_id: str,
    type: str,
    fields: dict,
    tags: dict | None = None,
    raw: str | None = None,
    confidence: float = 1.0,
) -> ToolResult:
    try:
        from backend.db.models import Observation
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            obs = Observation(
                user_id=user_id,
                type=type,
                fields=fields,
                tags=tags or {},
                raw=raw,
                confidence=confidence,
            )
            session.add(obs)
            await session.commit()
            await session.refresh(obs)
            return ok({"id": obs.id, "type": obs.type})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("log_observation failed")
        return degraded(f"db error: {exc}")
