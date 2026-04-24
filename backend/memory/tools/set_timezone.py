"""set_timezone — update the user's operational timezone.

This writes to `users.timezone`, which is the operational source of truth for:
- local "now" rendering in runtime context
- local calendar period bounds (today/this_week/last_week)
- time parsing for reminders/schedules

It also mirrors the new value into the bitemporal facts table (predicate
"current_timezone") so the history layer records when each belief became
current. The operational read path is unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.memory.time import timezone_label
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)


async def record_timezone_fact(
    user_id: str,
    tz: str,
    *,
    predicate: str = "current_timezone",
    source: str = "user_correction",
) -> str | None:
    """Best-effort mirror of a timezone write into the bitemporal facts table.

    Decision matrix:
      - no existing current belief → record_fact
      - existing belief equals new tz → no-op
      - existing belief differs → update_fact (state change, not correction)

    Returns the fact id if a row was inserted, None otherwise. Never raises —
    a bitemporal failure must never block the operational write.
    """
    try:
        from backend.memory.facts import get_current, record_fact, update_fact
        from backend.db.session import async_session
    except Exception:
        logger.exception("record_timezone_fact: imports failed")
        return None

    try:
        async with async_session() as session:
            current = await get_current(
                session, user_id=user_id, subject="user", predicate=predicate
            )
            if current is not None and current.object == tz:
                return None
            if current is None:
                new = await record_fact(
                    session,
                    user_id=user_id,
                    subject="user",
                    predicate=predicate,
                    object=tz,
                    source=source,
                )
            else:
                new = await update_fact(
                    session,
                    old_id=current.id,
                    new_object=tz,
                    source=source,
                )
            await session.commit()
            return new.id
    except Exception:
        logger.exception(
            "record_timezone_fact: bitemporal write failed user=%s pred=%s",
            user_id[:8], predicate,
        )
        return None

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


@instrument_memory_op("postgres.users")
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

    await record_timezone_fact(
        user_id, tz, predicate="current_timezone", source=str(source or "user_correction")
    )

    return ok({"timezone": tz})
