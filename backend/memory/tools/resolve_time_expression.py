"""resolve_time_expression — parse a natural-language time expression.

Deterministic regex-based resolver. Anchors wall-clock expressions ("at 6pm",
"last tuesday", "in 30 minutes") to the user's IANA timezone and returns a
UTC-aware ISO string suitable for use as `t_valid` in bi-temporal queries.

Supported expressions
---------------------
- absolute: "now", "today", "yesterday", "tomorrow"
- weekday: "last monday" .. "last sunday", "next monday" .. "next sunday"
- relative past: "N minutes/hours/days/weeks ago"
- relative future: "in N minutes/hours/days"
- clock: "at 6pm", "at 9:30am", "6 pm" (today, rolls to tomorrow if past)

Returns degraded when the expression cannot be parsed. Callers can inspect
`payload.reason` to tell the user.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from backend.memory.time import (
    DEFAULT_TIMEZONE,
    aware_utc,
    utcnow_naive,
    zone,
)
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Resolve a natural-language time expression (e.g. 'last tuesday', "
    "'3 hours ago', 'tomorrow at 6pm') to a concrete UTC ISO timestamp "
    "anchored in the user's timezone. Use before querying bi-temporal facts "
    "or scheduling. "
    "Do NOT use for expressions already in ISO form, for free-form "
    "durations like 'a few days' (resolve by asking the user), or when "
    "the expression has no time dimension."
)

INPUT_SCHEMA = {
    "type": "object",
    "required": ["expression"],
    "properties": {
        "expression": {
            "type": "string",
            "description": "Natural-language time phrase, e.g. 'last friday at 7pm'.",
        },
        "now": {
            "type": "string",
            "description": (
                "Optional ISO timestamp to anchor 'now' (for deterministic "
                "testing). Defaults to real wall-clock now."
            ),
        },
    },
}


_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_WEEKDAY_RE = re.compile(
    r"\b(last|next|this)\s+(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE
)
_RELATIVE_PAST_RE = re.compile(
    r"\b(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs|day|days|week|weeks)\s+ago\b",
    re.IGNORECASE,
)
_RELATIVE_FUTURE_RE = re.compile(
    r"\bin\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs|day|days|week|weeks)\b",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE
)


def _unit_to_timedelta(n: int, unit: str) -> timedelta:
    unit = unit.lower()
    if unit.startswith("min"):
        return timedelta(minutes=n)
    if unit.startswith("hour") or unit.startswith("hr"):
        return timedelta(hours=n)
    if unit.startswith("day"):
        return timedelta(days=n)
    if unit.startswith("week"):
        return timedelta(weeks=n)
    return timedelta()


def _parse_now(now: str | datetime | None) -> datetime:
    if isinstance(now, datetime):
        return aware_utc(now)
    if isinstance(now, str) and now.strip():
        try:
            return aware_utc(datetime.fromisoformat(now.strip().replace("Z", "+00:00")))
        except ValueError:
            logger.warning("resolve_time_expression: bad 'now' %r, falling back", now)
    return aware_utc(utcnow_naive())


def _apply_clock_to_date(base: date, match: re.Match[str], tz) -> datetime:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    local = datetime.combine(base, time(hour % 24, minute, 0), tzinfo=tz)
    return local


def _resolve_local(expression: str, now_utc: datetime, tz) -> datetime | None:
    """Return a tz-aware local datetime, or None if unparseable."""
    expr = expression.strip().lower()
    now_local = now_utc.astimezone(tz)

    if expr in ("now", "right now"):
        return now_local
    if expr == "today":
        return now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if expr == "yesterday":
        return (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if expr == "tomorrow":
        return (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    m = _RELATIVE_PAST_RE.search(expr)
    if m:
        return now_local - _unit_to_timedelta(int(m.group(1)), m.group(2))

    m = _RELATIVE_FUTURE_RE.search(expr)
    if m:
        return now_local + _unit_to_timedelta(int(m.group(1)), m.group(2))

    m = _WEEKDAY_RE.search(expr)
    if m:
        direction = m.group(1).lower()
        target_dow = _WEEKDAYS[m.group(2).lower()]
        today_dow = now_local.weekday()
        delta = (target_dow - today_dow) % 7
        if direction == "last":
            delta = -((today_dow - target_dow) % 7) if today_dow != target_dow else -7
        elif direction == "next":
            delta = delta or 7
        base_local = (now_local + timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
        clock = _CLOCK_RE.search(expr)
        if clock:
            return _apply_clock_to_date(base_local.date(), clock, tz)
        return base_local

    clock = _CLOCK_RE.search(expr)
    if clock:
        target = _apply_clock_to_date(now_local.date(), clock, tz)
        if target <= now_local:
            target += timedelta(days=1)
        return target

    return None


@instrument_memory_op("time")
async def resolve_time_expression(
    user_id: str,
    *,
    expression: str,
    now: str | datetime | None = None,
) -> ToolResult:
    """Resolve a natural-language time expression to a UTC ISO timestamp."""
    if not expression or not expression.strip():
        return degraded("empty expression")

    tz_name = await _load_user_timezone(user_id)
    tz = zone(tz_name)
    now_utc = _parse_now(now)

    resolved_local = _resolve_local(expression, now_utc, tz)
    if resolved_local is None:
        return degraded(f"could not parse {expression!r}")

    resolved_utc = resolved_local.astimezone(timezone.utc)
    return ok(
        {
            "at": resolved_utc.isoformat(timespec="seconds"),
            "timezone": tz_name or DEFAULT_TIMEZONE,
            "interpreted_as": resolved_local.isoformat(timespec="seconds"),
        }
    )


async def _load_user_timezone(user_id: str) -> str | None:
    """Best-effort DB lookup. Returns None if unavailable (tests, CLI)."""
    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        return None

    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            return str(user.timezone).strip() if user and user.timezone else None
    except Exception:
        return None
