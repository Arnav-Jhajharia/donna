"""Schedule materializer for attentions with a ``scheduled`` cadence.

Every live attention with ``cadence.type=scheduled`` should have a single
pending ``DonnaSchedule`` row representing its next fire. The existing
``schedule_worker`` then fires that row at ``fire_at``.

Today's schedule_worker handles the FIRING. The materializer handles the
ENQUEUEING — ensures rows exist for every card type that needs a cron,
not just ``card=ping``. Tally daily summaries, brief weekly digests, etc.

Idempotent: walks every live scheduled attention; if there's already a
pending row, it skips. Otherwise it calls ``materialize_next_fire``.

Polls every 5 minutes — cheap (a single SELECT and a small INSERT per
new attention). Catches newly-promoted attentions quickly without being
chatty.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from db.models import AttentionRow, DonnaSchedule, User
from db.session import async_session

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 300.0  # 5 min


async def _has_pending(attention_id: str) -> bool:
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(DonnaSchedule)
                    .where(DonnaSchedule.attention_id == attention_id)
                    .where(DonnaSchedule.fired == False)  # noqa: E712
                    .where(DonnaSchedule.status == "pending")
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
    except Exception:
        logger.exception(
            "attention_schedule_materializer: pending check failed att=%s",
            attention_id[:8],
        )
        return True  # fail closed — don't double-enqueue on a transient error


async def _ensure_pending_fire(att_row: AttentionRow, user: User) -> bool:
    """Materialize the next fire for one attention. Returns True if enqueued."""
    if await _has_pending(att_row.id):
        return False

    # Hydrate the in-memory Attention so we have the typed cadence.
    try:
        from donna.attention.firing import materialize_next_fire
        from donna.attention.store import AttentionStore

        store = AttentionStore()
        attention = store.get(att_row.id)
    except Exception:
        logger.exception(
            "attention_schedule_materializer: store.get failed att=%s",
            att_row.id[:8],
        )
        return False

    if attention is None:
        return False

    cadence_type = getattr(
        getattr(attention.spec, "cadence", None), "type", None
    )
    cad_value = getattr(cadence_type, "value", None)
    if cad_value not in ("scheduled", "one_shot", "recurring"):
        return False

    try:
        sched_id = await materialize_next_fire(
            attention,
            user_id=str(user.id),
            user_phone=user.phone,
            user_tz=user.timezone or "Asia/Kolkata",
            origin="attention_schedule_materializer",
        )
        if sched_id:
            logger.info(
                "schedule_materializer: enqueued att=%s sched=%s card=%s",
                att_row.id[:8],
                sched_id[:8],
                att_row.card,
            )
            return True
    except Exception:
        logger.exception(
            "schedule_materializer: materialize_next_fire raised att=%s",
            att_row.id[:8],
        )
    return False


async def _tick() -> int:
    n_enqueued = 0
    try:
        async with async_session() as session:
            stmt = (
                select(AttentionRow, User)
                .join(User, AttentionRow.user_id == User.id)
                .where(AttentionRow.status == "live")
                .where(AttentionRow.cadence_type.in_(("scheduled", "one_shot", "recurring")))
            )
            rows = (await session.execute(stmt)).all()
    except Exception:
        logger.exception("schedule_materializer: list failed")
        return 0

    for att_row, user in rows:
        try:
            if await _ensure_pending_fire(att_row, user):
                n_enqueued += 1
        except Exception:
            logger.exception(
                "schedule_materializer: ensure raised att=%s",
                att_row.id[:8],
            )
    return n_enqueued


async def run_forever(*, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("schedule_materializer: tick raised")
        await asyncio.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        n = asyncio.run(_tick())
        print(f"enqueued {n} schedule rows")
    else:
        asyncio.run(run_forever(poll_interval_s=args.poll))


if __name__ == "__main__":
    main()
