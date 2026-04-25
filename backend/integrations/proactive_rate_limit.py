"""Rate limiting + quiet hours for proactive pings.

Single source of truth for "should we wake the user up right now?"
Quota: 3/day per user. Cooldown: 30 minutes since last fired ping.
Quiet hours: derived from user's wake_time / sleep_time facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from db.models import ProactivePing


_DAILY_QUOTA = 3
_COOLDOWN = timedelta(minutes=30)


@dataclass(frozen=True)
class FireDecision:
    allowed: bool
    reason: str  # "ok" | "cooldown:Xs" | "quota:N/day" | "quiet:HH:MM-HH:MM"


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


async def can_fire_proactive(
    user_id: str, source: str, now: datetime | None = None
) -> FireDecision:
    if now is None:
        now = _utcnow()

    sleep_raw, wake_raw = await _load_user_quiet_hours(user_id)
    sleep_at = _parse_hhmm(sleep_raw)
    wake_at = _parse_hhmm(wake_raw)
    if sleep_at and wake_at:
        # Naive: treat `now` as already in user-local TZ. Production should
        # convert via zoneinfo using the user's timezone column.
        if _in_quiet_window(now.time(), sleep_at, wake_at):
            return FireDecision(
                allowed=False,
                reason=f"quiet:{sleep_raw}-{wake_raw}",
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
) -> None:
    async with _session_factory()() as session:
        session.add(
            ProactivePing(
                user_id=user_id,
                source=source,
                message_ref=message_ref,
                fired_at=at or _utcnow(),
                suppressed_reason=suppressed_reason,
            )
        )
        await session.commit()
