"""list_rules — Tier 2 procedural rules inferred from observations."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List inferred procedural rules about this user's behavior and preferences. "
    "Use to ground responses in what's consistently been true for them."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "description": "tier1 | tier2"},
        "limit": {"type": "integer", "default": 20},
    },
    "required": [],
}


@instrument_memory_op("postgres.rules")
async def list_rules(
    user_id: str, type: str | None = None, limit: int = 20
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import ProceduralRule
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            stmt = (
                select(ProceduralRule)
                .where(ProceduralRule.user_id == user_id)
                .order_by(ProceduralRule.created_at.desc())
                .limit(limit)
            )
            if type:
                stmt = stmt.where(ProceduralRule.type == type)
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return degraded("db error")
    if not rows:
        return no_hits()
    return ok(
        [
            {"id": r.id, "rule": r.rule, "type": r.type, "confidence": r.confidence}
            for r in rows
        ]
    )
