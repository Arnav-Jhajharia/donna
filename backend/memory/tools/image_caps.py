"""Caps + record-keeping for the image tool.

Two public async entry points:

- `check(user_id)` — returns a CapDecision telling the caller whether to allow
  the image. Looks at the last 7 days of `sent` rows in image_tool_events and
  applies cooldown + weekly cap.
- `record(user_id, status, prompt_hash)` — writes a single row describing a
  terminal outcome of an image-tool invocation.

Status values used elsewhere (PreToolUse hook, tool wrapper, PostToolUse hook):
  sent | denied_cooldown | denied_cap | failed_provider | failed_safety

The decision logic is a pure function `_decide` so unit tests don't need a DB.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from donna_runtime.config import IMAGE_COOLDOWN_HOURS, IMAGE_WEEKLY_CAP

logger = logging.getLogger(__name__)

Status = Literal[
    "sent",
    "denied_cooldown",
    "denied_cap",
    "failed_provider",
    "failed_safety",
]


@dataclass(frozen=True)
class CapDecision:
    allowed: bool
    reason: str = ""  # empty when allowed; short fall-through string when denied
    status: str = ""  # denied_cooldown | denied_cap | "" when allowed

    @classmethod
    def allow(cls) -> "CapDecision":
        return cls(allowed=True)

    @classmethod
    def deny_cooldown(cls, resets_in_hours: float) -> "CapDecision":
        h = max(1, round(resets_in_hours))
        return cls(
            allowed=False,
            reason=(
                f"image cap hit: another image in about {h}h. "
                f"no image this turn."
            ),
            status="denied_cooldown",
        )

    @classmethod
    def deny_cap(cls, resets_in_days: float) -> "CapDecision":
        d = max(1, round(resets_in_days))
        return cls(
            allowed=False,
            reason=(
                f"image cap hit: weekly limit reached, resets in about {d}d. "
                f"no image this turn."
            ),
            status="denied_cap",
        )


def _decide(now: datetime, sent_times: list[datetime]) -> CapDecision:
    """Pure decision logic. Times must be aware or all-naive UTC; we coerce."""
    window_start = now - timedelta(days=7)
    recent = [t for t in sent_times if _as_naive_utc(t) >= _as_naive_utc(window_start)]
    if len(recent) >= IMAGE_WEEKLY_CAP:
        oldest = min(recent, key=_as_naive_utc)
        resets_at = _as_naive_utc(oldest) + timedelta(days=7)
        days_left = (resets_at - _as_naive_utc(now)).total_seconds() / 86400
        return CapDecision.deny_cap(max(0.0, days_left))
    if recent:
        most_recent = max(recent, key=_as_naive_utc)
        elapsed_h = (
            _as_naive_utc(now) - _as_naive_utc(most_recent)
        ).total_seconds() / 3600
        if elapsed_h < IMAGE_COOLDOWN_HOURS:
            return CapDecision.deny_cooldown(IMAGE_COOLDOWN_HOURS - elapsed_h)
    return CapDecision.allow()


def _as_naive_utc(d: datetime) -> datetime:
    if d.tzinfo is None:
        return d
    return d.astimezone(timezone.utc).replace(tzinfo=None)


async def check(user_id: str) -> CapDecision:
    """Pull last-7d sent rows for the user and apply _decide."""
    if not user_id:
        return CapDecision.allow()  # runtime bug is reported elsewhere
    try:
        sent_times = await _fetch_recent_sent(user_id)
    except Exception:
        logger.exception("image_caps.check: DB unavailable; allowing by default")
        # Fail-open: we'd rather occasionally skip a cap than block Donna
        # entirely when the DB is flapping. The tool body still logs failure.
        return CapDecision.allow()
    return _decide(datetime.utcnow(), sent_times)


async def record(user_id: str, status: Status, prompt_hash: str | None = None) -> None:
    """Insert one image_tool_events row. Silently degrades on DB failure."""
    if not user_id or not status:
        return
    try:
        await _insert_event(user_id, status, prompt_hash)
    except Exception:
        logger.exception("image_caps.record: DB write failed (non-fatal)")


async def _fetch_recent_sent(user_id: str) -> list[datetime]:
    from sqlalchemy import select

    from backend.db.models import ImageToolEvent
    from backend.db.session import async_session

    cutoff = datetime.utcnow() - timedelta(days=7)
    async with async_session() as session:
        result = await session.execute(
            select(ImageToolEvent.created_at)
            .where(ImageToolEvent.user_id == user_id)
            .where(ImageToolEvent.status == "sent")
            .where(ImageToolEvent.created_at >= cutoff)
        )
        return [row[0] for row in result.all()]


async def _insert_event(
    user_id: str, status: Status, prompt_hash: str | None
) -> None:
    from backend.db.models import ImageToolEvent
    from backend.db.session import async_session

    async with async_session() as session:
        session.add(
            ImageToolEvent(
                user_id=user_id, status=status, prompt_hash=prompt_hash
            )
        )
        await session.commit()
