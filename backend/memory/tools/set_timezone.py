"""set_timezone — update the user's operational timezone.

This writes to `users.timezone`, which is the operational source of truth for:
- local "now" rendering in runtime context
- local calendar period bounds (today/this_week/last_week)
- time parsing for reminders/schedules
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.memory.time import timezone_label
from backend.memory.tools._shape import ToolResult, degraded, ok

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Set the user's timezone (IANA name like 'Asia/Singapore', 'America/New_York'). "
    "Use only when the user explicitly confirms or corrects their timezone."
)

INPUT_SCHEMA = {
    "type": "object",
    "required": ["timezone"],
    "properties": {
        "timezone": {"type": "string", "description": "IANA timezone, e.g. 'Asia/Singapore'."},
        "source": {"type": "string", "description": "Optional provenance label.", "default": "user_correction"},
    },
}


async def set_timezone(
    user_id: str,
    timezone: str,
    *,
    source: str = "user_correction",
) -> ToolResult:
    tz_raw = str(timezone or "").strip()
    if not user_id or not tz_raw:
        return degraded("missing user_id or timezone")

    try:
        ZoneInfo(tz_raw)
    except (ZoneInfoNotFoundError, ValueError):
        return degraded("invalid timezone (must be IANA name, e.g. 'Asia/Singapore')")

    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")

    tz = timezone_label(tz_raw)
    try:
        async with async_session() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if user is None:
                return degraded("user not found")

            user.timezone = tz
            try:
                goals = dict(user.onboarding_goals or {})
                goals["tz_done"] = True
                goals["tz_source"] = str(source or "user_correction")
                goals["tz_confirmed_at"] = datetime.now(timezone.utc).isoformat()
                user.onboarding_goals = goals
                flag_modified(user, "onboarding_goals")
            except Exception:
                logger.exception("set_timezone: failed to mark onboarding tz_done")

            # Best-effort: also reflect into facts so renderers can show it.
            try:
                facts = dict(user.facts or {})
                facts["current_timezone"] = {
                    "value": tz,
                    "source": str(source or "user_correction"),
                    "confidence": "high",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                user.facts = facts
                flag_modified(user, "facts")
            except Exception:
                logger.exception("set_timezone: failed to mirror timezone into facts")

            await session.commit()
    except Exception as exc:
        logger.exception("set_timezone failed")
        return degraded(f"db error: {exc}")

    return ok({"timezone": tz})
