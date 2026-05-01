"""Periodic nudge watcher.

Runs hourly. For each live attention whose ``surface_policy.nudge_policy``
specifies an ``if_silent_for_seconds`` threshold, computes how long since
the last contributing event (rollup ``last_event_at``) or last surface
fire (``last_surfaced_at``) — whichever is more recent — and asks the
attention's surfacer whether to fire a nudge.

If the surfacer returns ``kind=nudge``, the delivery layer fires the
WhatsApp burst (respecting per-user shadow/live mode).

Backoff: each user gets at most one nudge per attention per
``if_silent_for_seconds`` window. We use ``last_surfaced_at`` as the
debounce — once we nudge, we won't nudge again until the next window
elapses or the user logs something.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.memory.attention.delivery import deliver_surface
from backend.memory.attention.runtime import DeriveContext
from backend.memory.attention.surfacers import StaleNudgeSurfacer
from db.models import AttentionRow, User
from db.session import async_session

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 3600.0  # 1 hour


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


async def _tick() -> int:
    """Walk live attentions, compute silent_for_seconds, fire nudges."""
    n_fired = 0
    surfacer = StaleNudgeSurfacer()

    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore

        store = AttentionStore()
    except Exception:
        logger.exception("attention_nudge: store init failed")
        return 0

    try:
        async with async_session() as session:
            users = (
                await session.execute(select(User))
            ).scalars().all()
    except Exception:
        logger.exception("attention_nudge: user list failed")
        return 0

    now = _utcnow()
    for user in users:
        try:
            atts = store.list(user_id=str(user.id), status=AttentionStatus.LIVE)
        except Exception:
            logger.exception(
                "attention_nudge: list failed user=%s", str(user.id)[:8]
            )
            continue
        for a in atts:
            spec = getattr(a, "spec", None)
            policy = getattr(spec, "surface_policy", None) if spec else None
            nudge = getattr(policy, "nudge_policy", None) if policy else None
            if nudge is None:
                continue

            payload = await _read_payload(str(a.id))
            state = (payload or {}).get("current_state") or {}

            # Silent_for_seconds = now - max(last_event_at, last_surfaced_at).
            last_event = _parse_iso(state.get("last_event_at"))
            last_surfaced = _parse_iso(payload.get("last_surfaced_at_iso"))
            anchor = max(filter(None, [last_event, last_surfaced]), default=None)

            # Fall back to attention created_at if no events yet.
            created_at = _parse_iso(payload.get("created_at_iso"))
            anchor = anchor or created_at
            if anchor is None:
                continue
            silent_for = (now - anchor).total_seconds()
            if silent_for < 0:
                silent_for = 0

            # Build a state snapshot that includes silent_for_seconds for the surfacer.
            surfacer_state = dict(state)
            surfacer_state["silent_for_seconds"] = silent_for

            ctx = DeriveContext(
                user_id=str(user.id),
                user_local_now=now,
                user_local_day=now.date().isoformat(),
            )
            try:
                result = await surfacer.surface(
                    attention=a,
                    current_state=surfacer_state,
                    ctx=ctx,
                    trigger="nudge_watcher",
                )
            except Exception:
                logger.exception(
                    "attention_nudge: surfacer raised att=%s", str(a.id)[:8]
                )
                continue

            if result.kind != "nudge":
                continue

            try:
                fired = await deliver_surface(
                    user_id=str(user.id),
                    attention_id=str(a.id),
                    surface=result,
                )
                if fired:
                    n_fired += 1
            except Exception:
                logger.exception(
                    "attention_nudge: delivery raised att=%s", str(a.id)[:8]
                )

    if n_fired:
        logger.info("attention_nudge: fired %d nudges", n_fired)
    return n_fired


async def _read_payload(attention_id: str) -> dict | None:
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(AttentionRow).where(AttentionRow.id == attention_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            payload = dict(row.payload or {})
            if row.created_at:
                payload["created_at_iso"] = row.created_at.replace(
                    tzinfo=timezone.utc
                ).isoformat()
            if row.last_surfaced_at:
                payload["last_surfaced_at_iso"] = row.last_surfaced_at.replace(
                    tzinfo=timezone.utc
                ).isoformat()
            return payload
    except Exception:
        logger.exception("attention_nudge: payload read failed id=%s", attention_id[:8])
        return None


async def run_forever(*, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("attention_nudge: tick raised")
        await asyncio.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        n = asyncio.run(_tick())
        print(f"fired {n} nudges")
    else:
        asyncio.run(run_forever(poll_interval_s=args.poll))


if __name__ == "__main__":
    main()
