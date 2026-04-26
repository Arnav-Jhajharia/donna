"""Polling worker for the proactive attention pipeline.

Two passes on independent clocks:

- ``propose_pass`` — every ``PROPOSE_INTERVAL_SEC`` (default 30 min). For
  each active user, runs ``propose_and_shadow`` so proposers scan
  ambient signal and author SHADOW attentions.
- ``promote_pass`` — every ``PROMOTE_INTERVAL_SEC`` (default 15 min).
  Globally ticks every SHADOW attention via ``run_shadow_cycle``,
  promoting to OFFERED or archiving.

Gated on import-side by ``DONNA_ATTENTION_SCHEDULER=1``. ``run_forever``
itself does not check the env — the caller (api startup) decides.

Same shape as ``synthesis_worker.run_forever``: long-lived asyncio
loop, idempotent based on ``time.monotonic`` clocks. State is in-memory;
a restart re-fires both passes immediately, which is intentional — it
means a freshly deployed pod surfaces work fast.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Cadence — match the existing Scheduler defaults so the existing tests
# observe the same timing.
PROPOSE_INTERVAL_SEC = 30 * 60
PROMOTE_INTERVAL_SEC = 15 * 60

# Inner tick — wakes up to check whether either clock is due.
DEFAULT_POLL_INTERVAL_S = 60.0

# Active-user lookback for the propose pass. Matches the synthesis
# worker's window so a returning user starts producing proposals at the
# same moment their Living Profile starts refreshing.
ACTIVE_USER_LOOKBACK_DAYS = 30

# Concurrency cap for per-user propose calls. Each call may invoke
# Haiku/Sonnet; this cap keeps spend predictable.
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


async def run_propose_pass(
    *, max_concurrent: int = DEFAULT_MAX_CONCURRENT
) -> int:
    """Author SHADOW attentions for every active user. Returns user count."""
    from donna.attention.propose import propose_and_shadow

    user_ids = await _list_active_user_ids()
    if not user_ids:
        return 0

    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    async def _bounded(uid: str) -> None:
        async with semaphore:
            try:
                results = await propose_and_shadow(uid)
            except Exception:
                logger.exception(
                    "attention_worker: propose_and_shadow failed user=%s",
                    uid[:8],
                )
                return
            authored = sum(1 for r in results if r.attention is not None)
            if authored:
                logger.info(
                    "attention_worker: propose user=%s candidates=%d shadowed=%d",
                    uid[:8],
                    len(results),
                    authored,
                )

    await asyncio.gather(
        *(_bounded(uid) for uid in user_ids), return_exceptions=False
    )
    return len(user_ids)


async def run_promote_pass() -> int:
    """Tick all SHADOW attentions. Returns count of shadows ticked."""
    from donna.attention.promote import run_shadow_cycle

    # ``run_shadow_cycle`` is sync and does file I/O; offload to a thread
    # so the event loop stays responsive.
    results = await asyncio.to_thread(run_shadow_cycle)
    if results:
        promoted = sum(1 for r in results if r.action == "promoted")
        archived = sum(1 for r in results if r.action == "archived")
        logger.info(
            "attention_worker: promote ticked=%d promoted=%d archived=%d",
            len(results),
            promoted,
            archived,
        )
    return len(results)


async def run_forever(
    *,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    propose_interval_s: float = PROPOSE_INTERVAL_SEC,
    promote_interval_s: float = PROMOTE_INTERVAL_SEC,
) -> None:
    """Run the attention loop until cancelled.

    On startup both clocks are zero, so the first iteration fires both
    passes immediately. Subsequent ticks fire only when the
    corresponding clock is due.
    """
    last_propose_at = 0.0
    last_promote_at = 0.0

    logger.info(
        "attention_worker: starting (propose=%.0fs, promote=%.0fs, poll=%.0fs)",
        propose_interval_s,
        promote_interval_s,
        poll_interval_s,
    )

    while True:
        try:
            now = time.monotonic()
            if now - last_propose_at >= propose_interval_s:
                count = await run_propose_pass()
                last_propose_at = now
                if count:
                    logger.info(
                        "attention_worker: propose tick swept %d users", count
                    )
            if now - last_promote_at >= promote_interval_s:
                await run_promote_pass()
                last_promote_at = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("attention_worker: tick failed")
        await asyncio.sleep(poll_interval_s)
