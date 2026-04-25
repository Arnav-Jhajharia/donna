"""log_observation — record a countable event."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from backend.memory.time import coerce_to_utc_naive
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

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
        "event_time": {"type": "string", "description": "Optional ISO timestamp for when the event happened."},
        "confidence": {"type": "number", "default": 1.0},
    },
    "required": ["type", "fields"],
}


@instrument_memory_op("postgres.observations")
async def log_observation(
    user_id: str,
    type: str,
    fields: dict,
    tags: dict | None = None,
    raw: str | None = None,
    event_time: datetime | str | None = None,
    confidence: float = 1.0,
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import DonnaInstance, Observation, User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        async with async_session() as session:
            user = (
                await session.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            result = await session.execute(
                select(DonnaInstance).where(
                    DonnaInstance.user_id == user_id,
                    DonnaInstance.primitive == "track",
                    DonnaInstance.connector == "whatsapp_manual",
                    DonnaInstance.label == type,
                )
            )
            instance = result.scalar_one_or_none()
            if instance is None:
                instance = DonnaInstance(
                    user_id=user_id,
                    primitive="track",
                    connector="whatsapp_manual",
                    label=type,
                    config={"type": type},
                    status="active",
                )
                session.add(instance)
                await session.flush()
            obs = Observation(
                user_id=user_id,
                instance_id=instance.id,
                type=type,
                fields=fields,
                tags=tags or {},
                raw=raw,
                event_time=_coerce_event_time(event_time, timezone_name),
                confidence=confidence,
            )
            session.add(obs)
            await session.commit()
            await session.refresh(obs)
            refreshed = await _refresh_situation_brief(user_id)
            return ok({"id": obs.id, "type": obs.type, "situation_brief_refreshed": refreshed})
    except Exception as exc:
        logger.exception("log_observation failed")
        return degraded(f"db error: {exc}")


async def _refresh_situation_brief(user_id: str) -> bool:
    try:
        from backend.memory.tools.refresh_situation_brief import refresh_situation_brief_best_effort

        return await refresh_situation_brief_best_effort(user_id)
    except Exception:
        logger.exception("log_observation: situation brief refresh failed")
        return False


def _coerce_event_time(value: Any, timezone_name: str | None = None) -> datetime:
    return coerce_to_utc_naive(value, timezone_name)
