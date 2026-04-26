"""Morning proactive trigger.

Once a day, when the user enters their typical first-engage window AND
the nightly synth has produced a fresh ``watch_for_tomorrow``, donna
fires one short proactive message anchored on that watch + today_shape.

Hard rules:

- Fires AT MOST ONCE per user per local day.
- Only when ``watch_for_tomorrow`` is non-empty (no signal → no fire).
- Only inside the user's ``typical_first_engage_window`` (or within 30
  min of its midpoint, to forgive the worker poll cadence).
- Only when the rhythm has at least 3 days of data — cold-start
  protection so we don't blast a user we don't yet understand.
- Fired-today bookkeeping lives in ``users.living_profile`` under
  ``morning_proactive_last_fired_at``. Idempotent across restarts.

Design choice: this is a SEPARATE module from ``runner.py`` (the Exa
research loop). That runner produces fresh web signal; this trigger
lifts existing LP signal into chat. They're different shapes of
proactive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# Minimum days of rhythm data before we'll fire. Cold-start protection.
_MIN_RHYTHM_DAYS = 3

# Fudge factor: the worker polls every 5 min, so the engage window may
# be passed by a few minutes when we evaluate. ±30 min keeps the trigger
# loose enough to actually fire on most days without being lax enough to
# fire at random hours.
_ENGAGE_WINDOW_FUDGE = timedelta(minutes=30)


@dataclass(frozen=True)
class MorningTriggerDecision:
    """What ``maybe_fire_morning_check_in`` decided to do, for tests + logs."""

    fired: bool
    reason: str  # "fired" | "outside_window" | "no_watch" | "cold_start" | "already_fired_today" | "no_phone"


def _parse_window(window: str) -> tuple[time, time] | None:
    """Parse "HH:MM-HH:MM" → (start, end) ``time`` objects, or None."""
    if not window or "-" not in window:
        return None
    try:
        start_s, end_s = window.split("-", 1)
        start = datetime.strptime(start_s.strip(), "%H:%M").time()
        end = datetime.strptime(end_s.strip(), "%H:%M").time()
    except Exception:
        return None
    return start, end


def _inside_window(now_local: datetime, window: str) -> bool:
    parsed = _parse_window(window)
    if parsed is None:
        return False
    start, end = parsed
    today = now_local.date()
    start_dt = datetime.combine(today, start, tzinfo=now_local.tzinfo)
    end_dt = datetime.combine(today, end, tzinfo=now_local.tzinfo)
    if end_dt < start_dt:
        # Window crosses midnight — unusual for "first engage" but
        # tolerate by extending to next day.
        end_dt += timedelta(days=1)
    return (start_dt - _ENGAGE_WINDOW_FUDGE) <= now_local <= (end_dt + _ENGAGE_WINDOW_FUDGE)


def _rhythm_data_days(rhythm: dict) -> int:
    """Best-effort days-of-rhythm-data heuristic.

    The ``rhythm`` block doesn't carry a sample_size today. As a proxy
    we treat any non-empty rhythm record (typical_wake_window or
    typical_first_engage_window present) as evidence of at least one
    day. Synth refreshes nightly, so by the time both windows are set
    we've usually accumulated 3+ days.
    """
    if not isinstance(rhythm, dict):
        return 0
    has_wake = bool((rhythm.get("typical_wake_window") or "").strip())
    has_engage = bool((rhythm.get("typical_first_engage_window") or "").strip())
    days_proxy = int(rhythm.get("data_days") or 0)
    if days_proxy:
        return days_proxy
    # Best-effort proxy when the synth hasn't started writing data_days.
    return (3 if has_wake and has_engage else 1 if has_wake or has_engage else 0)


def _local_anchor_today(now_local: datetime, hour: int = 5) -> datetime:
    """Today's morning anchor, 05:00 user-local."""
    return now_local.replace(hour=hour, minute=0, second=0, microsecond=0)


def _last_fired_passes_anchor(
    last_fired_at_iso: str | None, anchor_local: datetime
) -> bool:
    """True when last fire is BEFORE today's anchor (i.e. we may fire again)."""
    if not last_fired_at_iso:
        return True
    try:
        last = datetime.fromisoformat(last_fired_at_iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last < anchor_local.astimezone(timezone.utc)


def _build_prompt(profile: dict) -> str:
    """Brief the brain receives for the morning ping."""
    watch = profile.get("watch_for_tomorrow") or []
    if isinstance(watch, str):
        watch = [watch]
    watch_lines = [str(w).strip() for w in watch if str(w).strip()]
    today_shape = (profile.get("today_shape") or "").strip()
    narrative = (profile.get("narrative") or profile.get("current_situation") or "").strip()

    parts = ["[morning proactive trigger]"]
    if narrative:
        parts.append(f"living profile read: {narrative[:400]}")
    if today_shape:
        parts.append(f"today shape: {today_shape[:300]}")
    if watch_lines:
        parts.append("watch_for_tomorrow:")
        for w in watch_lines[:4]:
            parts.append(f"- {w}")
    parts.append(
        "fire ONE short proactive message in donna's voice. anchor on the watch. "
        "no inventory of everything; pick the ONE thing that matters this morning. "
        "if there's nothing meaningful to say, end the turn with stay_silent."
    )
    return "\n".join(parts)


async def _lookup_user_phone(user_id: str) -> str | None:
    from sqlalchemy import select

    from db.models import User
    from db.session import async_session

    try:
        async with async_session() as session:
            row = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
        return getattr(row, "phone", None) if row else None
    except Exception:
        logger.exception(
            "morning trigger: phone lookup failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return None


async def _persist_last_fired(user_id: str, when: datetime) -> None:
    """Stash ``morning_proactive_last_fired_at`` on living_profile so
    the next tick honours the 1/day cap. Best-effort; logged on
    failure.
    """
    from sqlalchemy import select, update

    from db.models import User
    from db.session import async_session

    iso = when.astimezone(timezone.utc).isoformat()
    try:
        async with async_session() as session:
            row = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if row is None:
                return
            profile = dict(row.living_profile or {})
            profile["morning_proactive_last_fired_at"] = iso
            await session.execute(
                update(User).where(User.id == user_id).values(living_profile=profile)
            )
            await session.commit()
    except Exception:
        logger.exception(
            "morning trigger: failed to persist last_fired user=%s",
            user_id[:8] if user_id else "?",
        )


async def maybe_fire_morning_check_in(
    *,
    user_id: str,
    timezone_name: str,
    living_profile: dict | None,
    user_phone: str | None = None,
    now_local: datetime | None = None,
) -> MorningTriggerDecision:
    """Decide whether to fire and, if so, run the proactive turn.

    Pure decision logic up to the point of firing — easy to unit-test
    without hitting the brain or sending WhatsApp. ``user_phone`` is
    optional: when omitted we look it up just before firing (so the
    common gate-fail paths skip the DB hit).
    """
    profile = living_profile or {}
    if now_local is None:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = ZoneInfo("UTC")
        now_local = datetime.now(tz)

    rhythm = profile.get("rhythm") or {}
    if _rhythm_data_days(rhythm) < _MIN_RHYTHM_DAYS:
        return MorningTriggerDecision(fired=False, reason="cold_start")

    engage_window = (rhythm.get("typical_first_engage_window") or "").strip()
    if not engage_window or not _inside_window(now_local, engage_window):
        return MorningTriggerDecision(fired=False, reason="outside_window")

    watch = profile.get("watch_for_tomorrow") or []
    if isinstance(watch, str):
        watch = [watch]
    watch_lines = [str(w).strip() for w in watch if str(w).strip()]
    if not watch_lines:
        return MorningTriggerDecision(fired=False, reason="no_watch")

    anchor = _local_anchor_today(now_local)
    last_fired_iso = profile.get("morning_proactive_last_fired_at")
    if not _last_fired_passes_anchor(last_fired_iso, anchor):
        return MorningTriggerDecision(fired=False, reason="already_fired_today")

    if not user_phone:
        # Look it up now that all other gates passed; cheap one-row read.
        user_phone = await _lookup_user_phone(user_id)
    if not user_phone:
        return MorningTriggerDecision(fired=False, reason="no_phone")

    # All gates pass → run the brain in proactive mode.
    try:
        from delivery.whatsapp import WhatsAppChannel
        from donna_runtime.brain import donna_turn
        from donna_runtime.config import DonnaAgentConfig
    except Exception:
        logger.exception("morning trigger: import failed")
        return MorningTriggerDecision(fired=False, reason="cold_start")

    prompt = _build_prompt(profile)
    cfg = DonnaAgentConfig(mode="proactive", user_id=user_id, user_phone=user_phone)
    state: dict[str, Any] = {
        "user_id": user_id,
        "raw_input": prompt,
        "user_message": prompt,
        "phone": user_phone,
        "trigger": {
            "source": "morning_check_in",
            "fired_at": now_local.isoformat(),
        },
    }

    try:
        result = await donna_turn(state, cfg)
    except Exception:
        logger.exception(
            "morning trigger: brain failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return MorningTriggerDecision(fired=False, reason="cold_start")

    outbound = result.get("_outbound") if isinstance(result, dict) else None
    if outbound:
        try:
            wa = WhatsAppChannel()
            await wa.send_many(user_phone, list(outbound))
        except Exception:
            logger.exception(
                "morning trigger: whatsapp send failed user=%s",
                user_id[:8] if user_id else "?",
            )

    await _persist_last_fired(user_id, now_local)
    return MorningTriggerDecision(fired=True, reason="fired")
