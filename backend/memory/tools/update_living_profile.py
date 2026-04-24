"""update_living_profile — targeted patch between nightly runs."""
from __future__ import annotations

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Patch the user's Living Profile with a targeted key/value between nightly syntheses. "
    "Use sparingly — this is for observations that nightly will otherwise miss."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "patch": {"type": "object", "description": "Keys to merge into living_profile."},
    },
    "required": ["patch"],
}


@instrument_memory_op("living_profile")
async def update_living_profile(user_id: str, patch: dict) -> ToolResult:
    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                return no_hits()
            merged = dict(user.living_profile or {})
            merged.update(patch)
            user.living_profile = merged
            flag_modified(user, "living_profile")
            await session.commit()
            return ok({"keys": list(patch.keys())})
    except Exception:
        return degraded("db error")
