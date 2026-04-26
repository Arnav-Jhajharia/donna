"""Daily 24h-ahead sweep for the calendar spawner.

Mirrors the shape of ``attention_worker.run_forever``: long-lived
asyncio loop, idempotent, gated on ``DONNA_SPAWNERS=1`` by the
caller (api startup decides; this module never reads the env on
import). One loop covers all active users; the spawner's own dedup
ledger keeps re-spawns quiet.

The webhook hook in ``backend/integrations/calendar_ingest`` covers
the live-stream of new/updated events. This sweep covers two gaps:

- An event that was ingested before the spawner shipped (fresh users
  on first deploy).
- A clock-skew safety net — if a fire was 24h+ in the future when
  the event landed, the sweep re-evaluates everything inside the
  next 24h once a day and the dedup ledger guarantees it stays at
  most one spawn per (event_id, template_id).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


SWEEP_INTERVAL_SEC = 24 * 60 * 60
DEFAULT_POLL_INTERVAL_S = 60.0
SWEEP_LOOKAHEAD_HOURS = 24
ACTIVE_USER_LOOKBACK_DAYS = 30
DEFAULT_MAX_CONCURRENT = 4


async def _list_active_user_ids() -> list[str]:
    from sqlalchemy import select

    from db.models import User
    from db.session import async_session

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=ACTIVE_USER_LOOKBACK_DAYS
    )
    async with async_session() as session:
        rows = (
            await session.execute(
                select(User.id)
                .where(User.last_active_at.isnot(None))
                .where(User.last_active_at >= cutoff)
            )
        ).all()
    return [str(row[0]) for row in rows]


async def run_sweep_pass(
    *, max_concurrent: int = DEFAULT_MAX_CONCURRENT
) -> int:
    """Sweep upcoming calendar events for every active user.

    Returns the count of users swept. Per-user spawner failures are
    logged and swallowed so one bad user does not poison the loop.
    """
    from proactive.spawners import calendar as calendar_spawner

    user_ids = await _list_active_user_ids()
    if not user_ids:
        return 0

    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    async def _bounded(uid: str) -> None:
        async with semaphore:
            try:
                ids = await calendar_spawner.sweep_upcoming(
                    uid, hours=SWEEP_LOOKAHEAD_HOURS
                )
            except Exception:
                logger.exception(
                    "spawner_worker: sweep failed user=%s",
                    uid[:8],
                )
                return
            if ids:
                logger.info(
                    "spawner_worker: swept user=%s spawned=%d",
                    uid[:8],
                    len(ids),
                )

    await asyncio.gather(
        *(_bounded(uid) for uid in user_ids), return_exceptions=False
    )
    return len(user_ids)


async def run_forever(
    *,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    sweep_interval_s: float = SWEEP_INTERVAL_SEC,
) -> None:
    """Run the sweep loop until cancelled.

    First iteration fires the sweep immediately (matching
    attention_worker semantics), then waits ``sweep_interval_s``.
    """
    last_sweep_at = 0.0
    logger.info(
        "spawner_worker: starting (sweep=%.0fs, poll=%.0fs)",
        sweep_interval_s,
        poll_interval_s,
    )
    while True:
        try:
            now = time.monotonic()
            if now - last_sweep_at >= sweep_interval_s:
                count = await run_sweep_pass()
                last_sweep_at = now
                if count:
                    logger.info(
                        "spawner_worker: sweep tick covered %d users", count
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("spawner_worker: tick failed")
        await asyncio.sleep(poll_interval_s)
