"""Push-up feature handlers.

Two post_observation hooks:
  - ``prompt_pushup_after_workout`` — fires on workout observations.
    Creates a one-shot ``DonnaSchedule`` row that fires
    ``config.prompt_delay_sec`` later via the registered cron handler
    ``render_pushup_prompt``. Dedups against existing pending prompts
    so a workout-set logged in 5 quick observations only produces one
    "how many?" prompt.
  - ``update_pushup_state`` — fires on pushup observations. Increments
    today/week/total counters and tracks PR (max reps in one obs).

One cron handler:
  - ``render_pushup_weekly_recap`` — Sunday 18:00 recap of the week.

One scheduled handler (called by the schedule worker, not via cron):
  - ``render_pushup_prompt`` — composes the "how many push-ups?"
    Donna-voice text. Skips silently if the user already logged a
    pushup observation in the last hour (the prompt would be
    redundant).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import DonnaSchedule, Feature, Observation
from backend.features.handlers import (
    register_cron_handler,
    register_hook_handler,
)

logger = logging.getLogger(__name__)


# -- post_observation hook: schedule the prompt ----------------------------


async def prompt_pushup_after_workout(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    obs: Any,
) -> None:
    """When a workout lands, queue a one-shot 'how many?' prompt.

    Skipped when:
      - the observation isn't a workout (the dispatcher routes both
        workout AND pushup observations through this hook because the
        manifest declares both types; we only react to workout here)
      - a pending prompt schedule already exists (debounce)
      - a pushup observation has been logged in the last hour (the user
        already told us; no point asking)
    """
    if getattr(obs, "type", None) != "workout":
        return

    config = feature.config or {}
    delay_sec = int(config.get("prompt_delay_sec") or 60)

    if await _has_pending_prompt(
        session=session, user_id=user_id, feature_id=feature.id
    ):
        return
    if await _has_recent_pushup(
        session=session, user_id=user_id, within_seconds=3600
    ):
        return

    user = await _user_row(session=session, user_id=user_id)
    if user is None:
        return

    fire_at_utc = (
        datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    ).replace(tzinfo=None)
    schedule = DonnaSchedule(
        id=_uuid_str(),
        user_id=user_id,
        phone=user.phone or "",
        fire_at=fire_at_utc,
        origin="donna",
        recurrence=None,                # one-shot
        context={
            "source": "feature_reactive_prompt",
            "feature_id": feature.id,
            "trigger_obs_id": getattr(obs, "id", None),
        },
        recurrence_meta={
            "feature_id": feature.id,
            "feature_template_id": feature.template_id,
            "handler": "render_pushup_prompt",
            "spawned_by": "pushup_post_workout",
        },
        feature_id=feature.id,
        status="pending",
    )
    session.add(schedule)


async def _has_pending_prompt(
    *, session: AsyncSession, user_id: str, feature_id: str
) -> bool:
    """True iff a pending DonnaSchedule with handler='render_pushup_prompt'
    already exists for this user+feature.

    We can't easily express the JSONB filter portably across SQLite +
    Postgres, so the dedup loads candidate rows and checks the handler
    in Python. Cardinality is tiny (one feature, only future fires).
    """
    rows = (
        await session.execute(
            select(DonnaSchedule).where(
                DonnaSchedule.user_id == user_id,
                DonnaSchedule.feature_id == feature_id,
                DonnaSchedule.fired.is_(False),
                DonnaSchedule.status == "pending",
            )
        )
    ).scalars().all()
    for row in rows:
        meta = row.recurrence_meta or {}
        if (
            isinstance(meta, dict)
            and meta.get("handler") == "render_pushup_prompt"
        ):
            return True
    return False


async def _has_recent_pushup(
    *, session: AsyncSession, user_id: str, within_seconds: int
) -> bool:
    cutoff_utc = (
        datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    ).replace(tzinfo=None)
    rows = (
        await session.execute(
            select(Observation.id).where(
                Observation.user_id == user_id,
                Observation.type == "pushup",
                Observation.event_time >= cutoff_utc,
            )
            .limit(1)
        )
    ).scalars().all()
    return bool(rows)


# -- post_observation hook: maintain state ---------------------------------


async def update_pushup_state(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    obs: Any,
) -> None:
    """Increment counters when a pushup observation lands. Skip otherwise."""
    if getattr(obs, "type", None) != "pushup":
        return

    fields = obs.fields or {}
    raw_reps = fields.get("reps")
    try:
        reps = int(raw_reps) if raw_reps is not None else 0
    except (TypeError, ValueError):
        reps = 0

    user_tz = await _user_timezone(session=session, user_id=user_id)
    now_local = datetime.now(ZoneInfo(user_tz))
    today_start_utc = (
        now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ).astimezone(timezone.utc).replace(tzinfo=None)
    week_start_utc = (
        now_local - timedelta(days=7)
    ).astimezone(timezone.utc).replace(tzinfo=None)

    today_total = await _sum_reps_since(
        session=session, user_id=user_id, since_utc=today_start_utc
    )
    week_total = await _sum_reps_since(
        session=session, user_id=user_id, since_utc=week_start_utc
    )

    state = dict(feature.state or {})
    state["today_count"] = today_total
    state["week_count"] = week_total
    state["total_count"] = int(state.get("total_count") or 0) + reps
    state["pr"] = max(int(state.get("pr") or 0), reps)
    state["today_date"] = now_local.date().isoformat()
    state["last_logged_at"] = _utc_now_naive_iso()

    await session.execute(
        update(Feature)
        .where(Feature.id == feature.id)
        .values(state=state, updated_at=_utc_now_naive())
    )


async def _sum_reps_since(
    *, session: AsyncSession, user_id: str, since_utc: datetime
) -> int:
    rows = (
        await session.execute(
            select(Observation.fields).where(
                Observation.user_id == user_id,
                Observation.type == "pushup",
                Observation.event_time >= since_utc,
            )
        )
    ).scalars().all()
    total = 0
    for fields in rows:
        try:
            total += int((fields or {}).get("reps") or 0)
        except (TypeError, ValueError):
            continue
    return total


# -- Reactive prompt handler -----------------------------------------------


_PROMPT_VARIANTS: tuple[str, ...] = (
    "how many push-ups?",
    "push-up count?",
    "how many on that one?",
    "reps?",
    "how many push-ups did you get in?",
)


async def render_pushup_prompt(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    schedule_row: Any,
) -> str | None:
    """Compose the 'how many push-ups?' Donna-voice text.

    Skips silently if the user has logged a pushup observation since
    the schedule was created — they answered without prompting.
    """
    schedule_created = (
        schedule_row.created_at if schedule_row is not None else None
    )
    if schedule_created is not None:
        # If a pushup landed AFTER this schedule was queued, the user
        # already self-reported.
        rows = (
            await session.execute(
                select(Observation.id).where(
                    Observation.user_id == user_id,
                    Observation.type == "pushup",
                    Observation.event_time >= schedule_created,
                )
                .limit(1)
            )
        ).scalars().all()
        if rows:
            return None
    return random.choice(_PROMPT_VARIANTS)


# -- Cron: weekly recap ----------------------------------------------------


async def render_pushup_weekly_recap(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Feature,
    schedule_row: Any,
) -> str | None:
    """Sunday 18:00 recap.

    Body shape:
      no entries     → silent (skip)
      entries, no PR → "N this week."
      entries + PR   → "N this week. PR: M."
    """
    state = feature.state or {}
    user_tz = await _user_timezone(session=session, user_id=user_id)
    now_local = datetime.now(ZoneInfo(user_tz))
    week_start_utc = (
        now_local - timedelta(days=7)
    ).astimezone(timezone.utc).replace(tzinfo=None)

    week_total = await _sum_reps_since(
        session=session, user_id=user_id, since_utc=week_start_utc
    )
    if week_total == 0:
        return None

    pr = int(state.get("pr") or 0)
    if pr > 0:
        return f"{week_total} push-ups this week. PR: {pr}."
    return f"{week_total} push-ups this week."


# -- helpers ---------------------------------------------------------------


async def _user_row(*, session: AsyncSession, user_id: str):
    from db.models import User

    return (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()


async def _user_timezone(*, session: AsyncSession, user_id: str) -> str:
    user = await _user_row(session=session, user_id=user_id)
    return (user.timezone if user and user.timezone else "Asia/Singapore")


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_naive_iso() -> str:
    return _utc_now_naive().isoformat()


def _uuid_str() -> str:
    import uuid

    return str(uuid.uuid4())


# -- registration ----------------------------------------------------------


def register_handlers() -> None:
    register_hook_handler(
        "prompt_pushup_after_workout", prompt_pushup_after_workout
    )
    register_hook_handler("update_pushup_state", update_pushup_state)
    register_cron_handler("render_pushup_prompt", render_pushup_prompt)
    register_cron_handler(
        "render_pushup_weekly_recap", render_pushup_weekly_recap
    )


register_handlers()
