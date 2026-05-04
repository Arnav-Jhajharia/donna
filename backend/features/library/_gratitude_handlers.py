"""Gratitude feature handlers.

Two cron handlers + one post_observation hook. Same registration
pattern as ``_hydration_handlers``: ``register_handlers()`` is called at
module import time and is also callable from tests after
``_reset_for_tests`` wipes the registry.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Feature, Observation
from backend.features.handlers import (
    register_cron_handler,
    register_hook_handler,
)

logger = logging.getLogger(__name__)


# -- Cron: nightly prompt ---------------------------------------------------


_PROMPT_VARIANTS: tuple[str, ...] = (
    "what landed for you today?",
    "one thing that went right today?",
    "name one good thing — anything.",
    "who or what made today better?",
    "what surprised you today, in a good way?",
    "what's one thing worth noticing from today?",
)


async def render_gratitude_prompt(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    schedule_row: Any,
) -> str | None:
    """Compose tonight's prompt body.

    Skips silently if a gratitude observation already exists for today
    (the user already answered without being asked, or via an earlier
    fire). Otherwise rotates through the prompt variants.
    """
    user_tz = await _user_timezone(session=session, user_id=user_id)
    today_local = datetime.now(ZoneInfo(user_tz)).date()
    if await _has_observation_today(
        session=session,
        user_id=user_id,
        today_local=today_local,
        tz=user_tz,
    ):
        return None
    return random.choice(_PROMPT_VARIANTS)


# -- Cron: weekly recap -----------------------------------------------------


async def render_gratitude_weekly_recap(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    schedule_row: Any,
) -> str | None:
    """Compose Sunday evening's weekly recap.

    Reads the last 7 days of gratitude observations. Returns the count
    + a sample line, or skips silently when there are no entries.
    """
    user_tz = await _user_timezone(session=session, user_id=user_id)
    now_local = datetime.now(ZoneInfo(user_tz))
    cutoff_utc = (now_local - timedelta(days=7)).astimezone(timezone.utc).replace(tzinfo=None)

    rows = (
        await session.execute(
            select(Observation)
            .where(
                Observation.user_id == user_id,
                Observation.type == "gratitude",
                Observation.event_time >= cutoff_utc,
            )
            .order_by(Observation.event_time.desc())
        )
    ).scalars().all()

    if not rows:
        return None

    n = len(rows)
    sample_note = _sample_note(rows)
    if sample_note:
        return f"{n} this week. one of yours: \"{sample_note}\""
    if n == 1:
        return "one note this week. start of the muscle."
    return f"{n} notes this week."


def _sample_note(rows: list[Observation]) -> str | None:
    """Pick a representative note text — pseudo-random over the row ids."""
    candidates: list[str] = []
    for r in rows:
        fields = r.fields or {}
        note = (fields.get("note") or "").strip()
        if note:
            candidates.append(note)
    if not candidates:
        return None
    note = random.choice(candidates)
    if len(note) > 80:
        note = note[:77].rstrip() + "..."
    return note


# -- post_observation hook --------------------------------------------------


async def update_gratitude_state(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    obs: Any,
) -> None:
    """Update ``feature.state`` with today/week counters.

    Counters are computed authoritatively from observations rather than
    incrementally — gratitude has low write volume so a small re-count
    is fine and avoids the day/week rollover bookkeeping that hydration
    needs.
    """
    user_tz = await _user_timezone(session=session, user_id=user_id)
    now_local = datetime.now(ZoneInfo(user_tz))
    today_start_utc = (
        now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ).astimezone(timezone.utc).replace(tzinfo=None)
    week_start_utc = (
        now_local - timedelta(days=7)
    ).astimezone(timezone.utc).replace(tzinfo=None)

    today_count = (
        await session.execute(
            select(Observation.id)
            .where(
                Observation.user_id == user_id,
                Observation.type == "gratitude",
                Observation.event_time >= today_start_utc,
            )
        )
    ).scalars().all()
    week_count = (
        await session.execute(
            select(Observation.id)
            .where(
                Observation.user_id == user_id,
                Observation.type == "gratitude",
                Observation.event_time >= week_start_utc,
            )
        )
    ).scalars().all()

    state = dict(feature.state or {})
    state["today_count"] = len(today_count)
    state["week_count"] = len(week_count)
    state["today_date"] = now_local.date().isoformat()
    state["last_logged_at"] = _utc_now_naive_iso()

    await session.execute(
        update(Feature)
        .where(Feature.id == feature.id)
        .values(state=state, updated_at=_utc_now_naive())
    )


# -- helpers ----------------------------------------------------------------


async def _user_timezone(*, session: AsyncSession, user_id: str) -> str:
    from db.models import User

    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    return (user.timezone if user and user.timezone else "Asia/Singapore")


async def _has_observation_today(
    *,
    session: AsyncSession,
    user_id: str,
    today_local: date,
    tz: str,
) -> bool:
    today_start_utc = (
        datetime.combine(today_local, datetime.min.time(), ZoneInfo(tz))
    ).astimezone(timezone.utc).replace(tzinfo=None)
    rows = (
        await session.execute(
            select(Observation.id)
            .where(
                Observation.user_id == user_id,
                Observation.type == "gratitude",
                Observation.event_time >= today_start_utc,
            )
            .limit(1)
        )
    ).scalars().all()
    return bool(rows)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_naive_iso() -> str:
    return _utc_now_naive().isoformat()


# -- registration -----------------------------------------------------------


def register_handlers() -> None:
    """Idempotently (re-)register this feature's handlers."""
    register_cron_handler("render_gratitude_prompt", render_gratitude_prompt)
    register_cron_handler(
        "render_gratitude_weekly_recap", render_gratitude_weekly_recap
    )
    register_hook_handler("update_gratitude_state", update_gratitude_state)


register_handlers()
