"""schedule_reminder — persist a timed reminder into DonnaSchedule.

This is intentionally minimal: it writes a one-shot schedule row and relies on
the schedule worker to deliver it at `fire_at`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from backend.memory.time import coerce_to_utc_naive, utcnow_naive
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Schedule a one-shot reminder to be delivered later. "
    "Use only when the user explicitly asked for a timed reminder."
)

INPUT_SCHEMA = {
    "type": "object",
    "required": ["text"],
    "properties": {
        "text": {"type": "string", "description": "Reminder text to send at trigger time."},
        "fire_at": {"type": "string", "description": "Optional ISO timestamp for when to fire (local-aware if offset is provided)."},
        "in_minutes": {"type": "integer", "description": "Optional relative delay in minutes (alternative to fire_at)."},
        "origin": {"type": "string", "default": "user"},
    },
}


@instrument_memory_op("postgres.reminders")
async def schedule_reminder(
    user_id: str,
    *,
    text: str,
    fire_at: datetime | str | None = None,
    in_minutes: int | None = None,
    origin: str = "user",
) -> ToolResult:
    body = str(text or "").strip()
    if not user_id or not body:
        return degraded("missing user_id or text")

    try:
        from sqlalchemy import select

        from backend.db.models import DonnaSchedule, User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    try:
        async with async_session() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if user is None:
                return degraded("user not found")
            timezone_name = getattr(user, "timezone", None)
            phone = getattr(user, "phone", None)
            if not phone:
                return degraded("user missing phone")

            if in_minutes is not None:
                try:
                    minutes = int(in_minutes)
                except Exception:
                    return degraded("invalid in_minutes")
                if minutes <= 0 or minutes > 60 * 24 * 30:
                    return degraded("in_minutes out of range")
                fire = utcnow_naive() + timedelta(minutes=minutes)
            else:
                if fire_at is None or (isinstance(fire_at, str) and not fire_at.strip()):
                    return degraded("missing fire_at or in_minutes")
                fire = coerce_to_utc_naive(fire_at, timezone_name)

            row = DonnaSchedule(
                user_id=user_id,
                phone=phone,
                fire_at=fire,
                origin=str(origin or "user"),
                recurrence=None,
                context={
                    "messages": [{"type": "text", "body": body}],
                    "timezone": str(timezone_name or ""),
                },
                fired=False,
                status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return ok({"schedule_id": row.id, "fire_at": fire.isoformat(), "timezone": str(timezone_name or "")})
    except Exception as exc:
        logger.exception("schedule_reminder failed")
        return degraded(f"db error: {exc}")

