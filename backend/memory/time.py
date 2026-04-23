"""Timezone helpers for memory storage and rendering.

The root database stores timestamp columns as naive UTC datetimes. This module
keeps that convention explicit while making user-facing boundaries local to the
user's IANA timezone.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Singapore"


def zone(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def timezone_label(timezone_name: str | None) -> str:
    return zone(timezone_name).key


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def naive_utc(value: datetime) -> datetime:
    return aware_utc(value).replace(tzinfo=None)


def coerce_to_utc_naive(
    value: Any,
    timezone_name: str | None = None,
    *,
    default_now: bool = True,
) -> datetime:
    """Convert a model/user timestamp to naive UTC for DB storage.

    Offset-aware inputs are respected. Naive inputs are interpreted as local
    wall-clock time in ``timezone_name`` because Donna's users normally say
    "10:30" relative to their own timezone, not UTC.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(timezone.utc) if default_now else None
    else:
        dt = datetime.now(timezone.utc) if default_now else None

    if dt is None:
        raise ValueError("timestamp is required")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone(timezone_name))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def from_utc_naive(value: datetime, timezone_name: str | None = None) -> datetime:
    return aware_utc(value).astimezone(zone(timezone_name))


def format_local(value: datetime | None, timezone_name: str | None = None) -> str | None:
    if value is None:
        return None
    local = from_utc_naive(value, timezone_name)
    return f"{local:%Y-%m-%d %H:%M} {timezone_label(timezone_name)}"


def local_day_bounds(
    now: datetime | None = None,
    timezone_name: str | None = None,
    *,
    day_offset: int = 0,
) -> tuple[datetime, datetime]:
    tz = zone(timezone_name)
    local_now = aware_utc(now or datetime.now(timezone.utc)).astimezone(tz)
    target_date = local_now.date() + timedelta(days=day_offset)
    start_local = datetime.combine(target_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return naive_utc(start_local), naive_utc(end_local)


def local_week_bounds(
    now: datetime | None = None,
    timezone_name: str | None = None,
    *,
    week_offset: int = 0,
) -> tuple[datetime, datetime]:
    tz = zone(timezone_name)
    local_now = aware_utc(now or datetime.now(timezone.utc)).astimezone(tz)
    week_date = local_now.date() - timedelta(days=local_now.weekday()) + timedelta(weeks=week_offset)
    start_local = datetime.combine(week_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=7)
    return naive_utc(start_local), naive_utc(end_local)


def period_bounds(
    period: str | None,
    timezone_name: str | None = None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    key = (period or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key == "today":
        return local_day_bounds(now, timezone_name, day_offset=0)
    if key == "yesterday":
        return local_day_bounds(now, timezone_name, day_offset=-1)
    if key == "this_week":
        return local_week_bounds(now, timezone_name, week_offset=0)
    if key == "last_week":
        return local_week_bounds(now, timezone_name, week_offset=-1)
    return None
