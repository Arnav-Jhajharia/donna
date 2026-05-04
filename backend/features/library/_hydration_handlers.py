"""Hydration feature handlers — Phase 4 implementations.

The hydration manifest declares three handler names:

  - ``update_hydration_state``      (post_observation hook)
  - ``maybe_close_loop_on_glass_logged`` (post_turn hook — Phase 4b)
  - ``render_evening_summary``     (cron handler)

This module implements the live ones and registers them at import time.
``backend.features.registry.load_library`` imports each library module
which triggers the registration side-effect — no separate boot wiring
needed.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Feature
from backend.features.handlers import (
    register_cron_handler,
    register_hook_handler,
)

logger = logging.getLogger(__name__)


# -- post_observation hook --------------------------------------------------


async def update_hydration_state(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    obs: Any,
) -> None:
    """Increment ``feature.state.today_count`` and update streak.

    Called after each hydration observation is committed. The handler
    runs in the same session as ``log_observation`` so the state update
    rides on the same transaction (committed after this returns).

    State shape (versioned by manifest_version):
      today_count      — glasses logged today (user-local)
      today_date       — ISO date string, used to detect day rollover
      total_glasses    — lifetime glasses count
      streak_days      — consecutive days hitting target
      last_logged_at   — UTC-naive timestamp of last log
    """
    state = dict(feature.state or {})
    config = feature.config or {}

    user_tz = await _user_timezone(session=session, user_id=user_id)
    event_local_date = _local_date_of(obs.event_time, tz=user_tz)
    glasses = _glasses_from_fields(obs.fields or {})

    prev_today_date = state.get("today_date")
    prev_today_count = int(state.get("today_count") or 0)
    prev_total = int(state.get("total_glasses") or 0)
    prev_streak = int(state.get("streak_days") or 0)
    target = int(config.get("target_glasses") or 8)

    if prev_today_date != event_local_date.isoformat():
        # Day rollover — settle the streak from yesterday's count, then
        # reset today_count.
        prev_streak = _settle_streak(
            prev_today_date=prev_today_date,
            event_local_date=event_local_date,
            prev_today_count=prev_today_count,
            prev_streak=prev_streak,
            target=target,
        )
        today_count = glasses
    else:
        today_count = prev_today_count + glasses

    state["today_count"] = today_count
    state["today_date"] = event_local_date.isoformat()
    state["total_glasses"] = prev_total + glasses
    state["streak_days"] = prev_streak
    state["last_logged_at"] = _utc_now_naive_iso()

    await session.execute(
        update(Feature)
        .where(Feature.id == feature.id)
        .values(state=state, updated_at=_utc_now_naive())
    )


def _settle_streak(
    *,
    prev_today_date: str | None,
    event_local_date: date,
    prev_today_count: int,
    prev_streak: int,
    target: int,
) -> int:
    """Roll the streak forward / reset / preserve.

    Three cases:
      - No prior date: fresh feature, streak stays at whatever it was.
      - Yesterday's count hit target AND we're rolling to the next
        consecutive day → +1 streak.
      - Otherwise → reset to 0 (gap day or under-target).
    """
    if not prev_today_date:
        return prev_streak
    try:
        prev_date = date.fromisoformat(prev_today_date)
    except ValueError:
        return prev_streak
    expected_next = prev_date + timedelta(days=1)
    hit_target = prev_today_count >= target
    if event_local_date == expected_next and hit_target:
        return prev_streak + 1
    return 0


def _glasses_from_fields(fields: dict[str, Any]) -> int:
    """Pull the ``glasses`` count from observation fields.

    Defaults to 1 when the field is missing — a hydration observation
    without an explicit count almost always means "one glass."
    """
    raw = fields.get("glasses")
    if raw is None:
        return 1
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(0, n)


# -- cron handler -----------------------------------------------------------


async def render_evening_summary(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    schedule_row: Any,
) -> str | None:
    """Compose the 21:00 daily WhatsApp text from feature state.

    Returns the message body (or ``None`` to skip silently). The
    schedule worker takes responsibility for actually delivering — this
    handler is a pure renderer so it stays unit-testable.
    """
    state = feature.state or {}
    config = feature.config or {}
    user_tz = await _user_timezone(session=session, user_id=user_id)
    today_local = datetime.now(ZoneInfo(user_tz)).date().isoformat()

    if state.get("today_date") != today_local:
        # No logs today — stay silent rather than nag a clean miss.
        return None

    count = int(state.get("today_count") or 0)
    target = int(config.get("target_glasses") or 8)
    streak = int(state.get("streak_days") or 0)

    if count >= target and streak >= 2:
        return f"{count} glasses today. {streak}-day streak. solid."
    if count >= target:
        return f"{count} glasses today. target hit. nice."
    short_by = target - count
    if short_by == 1:
        return f"{count}/{target}. one short. one before bed?"
    return f"{count}/{target}. {short_by} short. tomorrow."


# -- helpers ----------------------------------------------------------------


async def _user_timezone(*, session: AsyncSession, user_id: str) -> str:
    """Resolve user TZ for date math. Defaults to Asia/Singapore."""
    from db.models import User

    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    return (user.timezone if user and user.timezone else "Asia/Singapore")


def _local_date_of(ev: datetime | None, *, tz: str) -> date:
    """Project an observation's UTC-naive event_time into ``tz``'s local date."""
    if ev is None:
        return datetime.now(ZoneInfo(tz)).date()
    if ev.tzinfo is None:
        ev = ev.replace(tzinfo=timezone.utc)
    return ev.astimezone(ZoneInfo(tz)).date()


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_naive_iso() -> str:
    return _utc_now_naive().isoformat()


# -- registration -----------------------------------------------------------


def register_handlers() -> None:
    """Idempotently (re-)register this feature's handlers.

    Called at module import time AND callable from tests so handler
    registration survives ``handlers._reset_for_tests()`` between
    cases. Re-registration overrides whatever was previously stored
    under the same name.
    """
    register_hook_handler("update_hydration_state", update_hydration_state)
    register_cron_handler("render_evening_summary", render_evening_summary)


register_handlers()
