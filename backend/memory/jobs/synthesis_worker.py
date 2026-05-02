"""Polling worker for nightly + morning Living Profile synthesis.

Runs as a long-lived loop (analogous to ``schedule_worker.run_forever``).
On each tick:

1. Lists active users (those who messaged in the last 30 days).
2. For each user, computes the user-local time and decides whether
   either the nightly full synthesis (anchor: 02:00 local) or the
   morning digest refresh (anchor: 05:00 local) is due.
3. Fires the appropriate synthesizer, then moves on.

Idempotency comes from the timestamps written into
``users.living_profile`` by the synthesizers themselves:

- ``generated_at`` — last full synthesis.
- ``yesterday_refreshed_at`` — last morning digest merge.

Both are ISO-8601 UTC strings. A run is "due" when the most recent
local-anchor moment (02:00 or 05:00 in the user's tz) is *after* the
relevant stored timestamp. This means we never run twice for the same
local day, and a worker that comes up late catches the missed run on
the same day.

This worker does NOT use ``DonnaSchedule``. That table is purpose-built
for WhatsApp deliveries; synthesis is an internal job with no
user-visible message.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Anchor hours in the user's local timezone.
NIGHTLY_FULL_ANCHOR_HOUR = 2
MORNING_DIGEST_ANCHOR_HOUR = 5

# Active user window. We do not synthesize for users who have gone fully
# silent — wastes Haiku spend. 30 days matches the Living Profile's
# observation lookback so a returning user gets a fresh profile.
ACTIVE_USER_LOOKBACK_DAYS = 30

# Default tick cadence. Synthesis is per-day-per-user, so a slow tick is
# fine. 5 minutes balances "fire close to the anchor hour" with "do not
# hammer the DB."
DEFAULT_POLL_INTERVAL_S = 300.0

# Per-tick concurrency limit to keep Haiku spend predictable and avoid
# DB contention spikes when many users cross the anchor at once.
DEFAULT_MAX_CONCURRENT = 4


def _last_anchor_local(now_local: datetime, anchor_hour: int) -> datetime:
    """Return the most recent ``anchor_hour:00`` moment at or before ``now_local``.

    If we are past ``anchor_hour`` today, that is today's anchor. Otherwise
    it was yesterday's. Always tz-aware in the same zone as ``now_local``.
    """
    today_anchor = now_local.replace(
        hour=anchor_hour, minute=0, second=0, microsecond=0
    )
    if now_local >= today_anchor:
        return today_anchor
    return today_anchor - timedelta(days=1)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_full_due(
    *, now_local: datetime, generated_at: str | None
) -> bool:
    last_anchor_utc = _last_anchor_local(now_local, NIGHTLY_FULL_ANCHOR_HOUR).astimezone(
        timezone.utc
    )
    last_run = _parse_iso(generated_at)
    if last_run is None:
        return True
    return last_run < last_anchor_utc


def is_morning_due(
    *, now_local: datetime, yesterday_refreshed_at: str | None
) -> bool:
    if now_local.hour < MORNING_DIGEST_ANCHOR_HOUR:
        return False
    last_anchor_utc = _last_anchor_local(
        now_local, MORNING_DIGEST_ANCHOR_HOUR
    ).astimezone(timezone.utc)
    last_run = _parse_iso(yesterday_refreshed_at)
    if last_run is None:
        return True
    return last_run < last_anchor_utc


async def _list_active_users() -> list[tuple[str, str, dict | None]]:
    """Return ``(user_id, timezone, living_profile)`` for active users."""
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=ACTIVE_USER_LOOKBACK_DAYS
    )
    async with async_session() as session:
        rows = (
            await session.execute(
                select(User.id, User.timezone, User.living_profile)
                .where(User.last_active_at.isnot(None))
                .where(User.last_active_at >= cutoff)
            )
        ).all()
    return [(row[0], row[1] or "UTC", row[2]) for row in rows]


def _user_local_now(timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


async def _run_one(
    user_id: str,
    timezone_name: str,
    living_profile: dict | None,
    *,
    full_runner: Callable[[str], Awaitable[dict | None]],
    morning_runner: Callable[[str], Awaitable[dict | None]],
) -> None:
    now_local = _user_local_now(timezone_name)
    profile = living_profile or {}

    full_just_ran = False
    if is_full_due(
        now_local=now_local, generated_at=profile.get("generated_at")
    ):
        try:
            await full_runner(user_id)
            full_just_ran = True
        except Exception:
            logger.exception(
                "synthesis_worker: full pass failed user=%s", user_id[:8]
            )

    if not full_just_ran and is_morning_due(
        now_local=now_local,
        yesterday_refreshed_at=profile.get("yesterday_refreshed_at"),
    ):
        try:
            await morning_runner(user_id)
        except Exception:
            logger.exception(
                "synthesis_worker: morning pass failed user=%s", user_id[:8]
            )

    # Independent of synth scheduling: every tick, see if the user is
    # currently in their typical first-engage window AND has a fresh
    # ``watch_for_tomorrow`` worth surfacing AND we haven't fired today.
    # The trigger has its own gates; cheap to call when they fail.
    try:
        from backend.web.proactive.triggers.morning import (
            maybe_fire_morning_check_in,
        )

        # Re-read profile in case morning_runner just refreshed it.
        await maybe_fire_morning_check_in(
            user_id=user_id,
            timezone_name=timezone_name,
            living_profile=profile,
            now_local=now_local,
        )
    except Exception:
        logger.exception(
            "synthesis_worker: morning trigger failed user=%s", user_id[:8]
        )

    # After Living Profile is fresh, run the L0 -> L1 fanout: derive
    # external watches from the user's full state (LP + recent chat +
    # observations + open loops) and reconcile them into subscriptions.
    # Each sub carries a cadence (daily/weekly/monthly) picked by the
    # deriver; the cadence-aware /search poller in run_proactive_worker
    # picks them up. We do NOT provision Exa websets+monitors anymore —
    # they cost ~10 credits per delivered row vs ~5 credits per
    # /search call, so polling is 15-30x cheaper for our budget.
    try:
        from backend.web.proactive.subscriptions import derive_and_reconcile
        result = await derive_and_reconcile(user_id)
        if result.derived_count or result.reconcile.created or result.reconcile.deactivated:
            logger.info(
                "synthesis_worker: derived=%d created=%d deactivated=%d user=%s",
                result.derived_count,
                result.reconcile.created,
                result.reconcile.deactivated,
                user_id[:8],
            )
    except Exception:
        logger.exception(
            "synthesis_worker: subscriptions reconcile failed user=%s",
            user_id[:8],
        )


async def run_once(
    *,
    full_runner: Callable[[str], Awaitable[dict | None]] | None = None,
    morning_runner: Callable[[str], Awaitable[dict | None]] | None = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
) -> int:
    """Dispatch synthesis work for all due users. Returns count attempted."""
    if full_runner is None or morning_runner is None:
        from backend.memory.synthesis.living_profile import (
            refresh_morning_digest,
            synthesize_full_profile,
        )

        full_runner = full_runner or synthesize_full_profile
        morning_runner = morning_runner or refresh_morning_digest

    users = await _list_active_users()
    if not users:
        return 0

    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    async def _bounded(user_id: str, tz_name: str, profile: dict | None) -> None:
        async with semaphore:
            await _run_one(
                user_id,
                tz_name,
                profile,
                full_runner=full_runner,
                morning_runner=morning_runner,
            )

    await asyncio.gather(
        *(_bounded(uid, tz, prof) for uid, tz, prof in users),
        return_exceptions=False,
    )
    return len(users)


async def run_forever(*, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    """Run the synthesis dispatch loop until cancelled."""
    while True:
        try:
            count = await run_once()
            if count:
                logger.info("synthesis_worker: tick swept %d users", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("synthesis_worker: tick failed")
        await asyncio.sleep(poll_interval_s)
