"""Rate limiting + quiet hours + topic dedup for proactive pings.

Single source of truth for "should we wake the user up right now?"
Quota: 3/day per user. Cooldown: 30 minutes since last fired ping.
Quiet hours: derived from user's wake_time / sleep_time facts.
Active-chat: deny when the user sent a message in the last 5 minutes
(the reactive turn will surface things naturally).
Topic cooldown: 30 minutes per ``topic_key`` so a long thread does not
re-fire on every reply.

Quiet-hours fallback: when ``sleep_time``/``wake_time`` user_facts are
unset but the user's timezone is set, default to 00:00–07:00 in their
local timezone. With no timezone, no quiet hours apply (we cannot tell
day from night safely).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from db.models import ChatMessage, ProactivePing


_DAILY_QUOTA = 3
_COOLDOWN = timedelta(minutes=30)
_TOPIC_COOLDOWN = timedelta(minutes=30)
_ACTIVE_CHAT_WINDOW = timedelta(minutes=5)

# Default quiet hours when the user has not set sleep/wake_time facts but
# we know their timezone. Conservative: midnight to 7am local time.
_DEFAULT_SLEEP = "00:00"
_DEFAULT_WAKE = "07:00"


@dataclass(frozen=True)
class FireDecision:
    allowed: bool
    reason: str
    # "ok" | "cooldown:Xs" | "topic_cooldown:Xs" | "quota:N/day"
    # | "quiet:HH:MM-HH:MM" | "active_chat:Xs"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_factory():
    # Lazy import so test monkeypatches of `backend.db.session.async_session`
    # are honored at call time.
    from backend.db.session import async_session

    return async_session


def _parse_hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        h, m = raw.strip().split(":")
        return time(hour=int(h), minute=int(m))
    except Exception:
        return None


def _in_quiet_window(
    now_local: time, sleep_at: time, wake_at: time
) -> bool:
    """True if now_local lies in the [sleep_at, wake_at) wraparound window."""
    if sleep_at <= wake_at:
        return sleep_at <= now_local < wake_at
    return now_local >= sleep_at or now_local < wake_at


async def _load_user_quiet_hours(
    user_id: str,
) -> tuple[str | None, str | None]:
    from backend.memory.user_facts.api import get_user_facts

    facts = await get_user_facts(user_id)
    sleep_fact = (facts or {}).get("sleep_time")
    wake_fact = (facts or {}).get("wake_time")
    sleep = getattr(sleep_fact, "value", None) if sleep_fact is not None else None
    wake = getattr(wake_fact, "value", None) if wake_fact is not None else None
    return sleep, wake


async def _load_user_timezone(user_id: str) -> str | None:
    """Best-effort timezone fetch — None on any error or missing user."""
    try:
        from db.models import User

        async with _session_factory()() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return None
            return getattr(user, "timezone", None) or None
    except Exception:
        return None


async def _resolve_quiet_hours(user_id: str) -> tuple[str | None, str | None]:
    """Return ``(sleep, wake)`` strings to apply, or ``(None, None)``.

    Order:
      1. explicit user_facts ``sleep_time`` / ``wake_time``,
      2. default ``00:00`` / ``07:00`` when the user has a timezone set,
      3. nothing.
    """
    sleep, wake = await _load_user_quiet_hours(user_id)
    if sleep and wake:
        return sleep, wake
    tz = await _load_user_timezone(user_id)
    if tz:
        return _DEFAULT_SLEEP, _DEFAULT_WAKE
    return None, None


async def _last_user_message_at(user_id: str) -> datetime | None:
    """Most-recent timestamp of a user-role chat message. None when absent."""
    async with _session_factory()() as session:
        row = (
            await session.execute(
                select(ChatMessage.created_at)
                .where(ChatMessage.user_id == user_id)
                .where(ChatMessage.role == "user")
                .order_by(ChatMessage.created_at.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        return None
    return row[0]


async def _last_topic_fire_at(
    user_id: str, topic_key: str
) -> datetime | None:
    """Most-recent ``fired_at`` for a non-suppressed ping on this topic."""
    async with _session_factory()() as session:
        row = (
            await session.execute(
                select(ProactivePing.fired_at)
                .where(ProactivePing.user_id == user_id)
                .where(ProactivePing.topic_key == topic_key)
                .where(ProactivePing.suppressed_reason.is_(None))
                .order_by(ProactivePing.fired_at.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        return None
    return row[0]


async def can_fire_proactive(
    user_id: str,
    source: str,
    *,
    topic_key: str | None = None,
    now: datetime | None = None,
) -> FireDecision:
    """Should the dispatcher fire a proactive ping now?

    Order of checks (cheapest-to-deny first): quiet hours, active chat,
    per-topic cooldown, global cooldown, daily quota.
    """
    if now is None:
        now = _utcnow()

    sleep_raw, wake_raw = await _resolve_quiet_hours(user_id)
    sleep_at = _parse_hhmm(sleep_raw)
    wake_at = _parse_hhmm(wake_raw)
    if sleep_at and wake_at:
        # Convert UTC ``now`` to the user's local time-of-day before
        # comparing. Without this, users far from UTC saw the quiet
        # window shifted by their offset (e.g. an Asia/Singapore user
        # hit ``quiet:00:00-07:00`` during their midday).
        tz_name = await _load_user_timezone(user_id)
        now_local_t = now.time()
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                now_local_t = (
                    now.replace(tzinfo=timezone.utc)
                    .astimezone(ZoneInfo(tz_name))
                    .time()
                )
            except Exception:
                pass
        if _in_quiet_window(now_local_t, sleep_at, wake_at):
            return FireDecision(
                allowed=False,
                reason=f"quiet:{sleep_raw}-{wake_raw}",
            )

    last_user_msg = await _last_user_message_at(user_id)
    if last_user_msg is not None:
        idle = now - last_user_msg
        if idle < _ACTIVE_CHAT_WINDOW:
            return FireDecision(
                allowed=False,
                reason=f"active_chat:{int(idle.total_seconds())}s",
            )

    if topic_key:
        last_topic = await _last_topic_fire_at(user_id, topic_key)
        if last_topic is not None and (now - last_topic) < _TOPIC_COOLDOWN:
            return FireDecision(
                allowed=False,
                reason=(
                    f"topic_cooldown:{int((now - last_topic).total_seconds())}s"
                ),
            )

    async with _session_factory()() as session:
        recent = (
            await session.execute(
                select(ProactivePing)
                .where(ProactivePing.user_id == user_id)
                .where(ProactivePing.suppressed_reason.is_(None))
                .where(ProactivePing.fired_at >= now - timedelta(days=1))
                .order_by(ProactivePing.fired_at.desc())
            )
        ).scalars().all()

    if recent:
        last = recent[0].fired_at
        if (now - last) < _COOLDOWN:
            return FireDecision(
                allowed=False,
                reason=f"cooldown:{int((now - last).total_seconds())}s",
            )

    if len(recent) >= _DAILY_QUOTA:
        return FireDecision(
            allowed=False, reason=f"quota:{len(recent)}/day"
        )

    return FireDecision(allowed=True, reason="ok")


async def record_ping(
    user_id: str,
    source: str,
    message_ref: str | None,
    at: datetime | None = None,
    suppressed_reason: str | None = None,
    *,
    topic_key: str | None = None,
) -> None:
    async with _session_factory()() as session:
        session.add(
            ProactivePing(
                user_id=user_id,
                source=source,
                message_ref=message_ref,
                topic_key=topic_key,
                fired_at=at or _utcnow(),
                suppressed_reason=suppressed_reason,
            )
        )
        await session.commit()
