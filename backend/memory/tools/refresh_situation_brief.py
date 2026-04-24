"""refresh_situation_brief — regenerate the stored temporal mental model."""
from __future__ import annotations

import logging

from backend.memory.synthesis.temporal_brief import BriefImplementation
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Regenerate Donna's deterministic temporal situation brief and store it under "
    "users.living_profile.situation_brief. Intended for nightly jobs and internal "
    "post-write maintenance, not casual model-facing writes."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "implementation": {
            "type": "string",
            "default": BriefImplementation.WINDOWED_TIMELINE.value,
        },
        "use_claude": {"type": "boolean", "default": False},
    },
    "required": [],
}


@instrument_memory_op("living_profile")
async def refresh_situation_brief(
    user_id: str,
    implementation: str = BriefImplementation.WINDOWED_TIMELINE.value,
    use_claude: bool = False,
) -> ToolResult:
    try:
        from backend.memory.synthesis.temporal_brief import synthesize_and_store_temporal_brief
    except Exception:
        return degraded("synthesis unavailable")

    try:
        brief = await synthesize_and_store_temporal_brief(
            user_id=user_id,
            implementation=implementation,
            use_claude=use_claude,
        )
    except Exception as exc:
        logger.exception("refresh_situation_brief failed")
        return degraded(f"synthesis error: {exc}")

    return ok(
        {
            "implementation": brief.implementation,
            "generated_at": brief.generated_at,
            "evidence_used": brief.evidence_used,
            "summary": brief.summary,
        }
    )


async def refresh_situation_brief_best_effort(user_id: str | None) -> bool:
    if not user_id:
        return False
    result = await refresh_situation_brief(user_id)
    return result.get("status") == "ok"
