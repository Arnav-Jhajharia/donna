"""Periodic sweep over live attentions.

Runs hourly. Three jobs:
  1. Day rollover — for each live attention whose ``current_state.day`` is
     before the user-local day, re-evaluate so today's rollup resets.
  2. Backstop for missed events — re-evaluate any attention whose
     ``last_update_at`` is older than 2 hours, in case an observation
     write hook didn't fire (worker race, db hiccup, etc.).
  3. External-stream poll — every tick, evaluate every live
     ``card=event_stream`` attention so its registered poller fetches new
     signal (gmail, stocks, github PRs, ...). The poller dedups via its
     own cursor; this loop just makes sure the poll happens.

Cheap: deterministic rollups for tally/open_loop, no LLM calls. Pollers
are I/O-bound but read from the local mirrors that webhook-driven
ingest already populates, so they don't burn external API quota.
Backstop sweep is the safety net — the primary path is event-driven via
``log_observation``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.memory.attention.engine import (
    evaluate_attention,
    evaluate_user_attentions,
)
from db.models import AttentionRow, User
from db.session import async_session

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 3600.0  # 1 hour
STALE_AFTER_HOURS = 2


def _user_local_day_iso(tz_name: str | None) -> str:
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).date().isoformat()


async def _stale_attentions() -> list[tuple[str, str, str]]:
    """Return ``(attention_id, user_id, reason)`` triples needing re-eval."""
    out: list[tuple[str, str, str]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
    cutoff_naive = cutoff.replace(tzinfo=None)
    try:
        async with async_session() as session:
            # Pull all live attentions and their owning user's tz.
            stmt = (
                select(AttentionRow, User.timezone)
                .join(User, AttentionRow.user_id == User.id)
                .where(AttentionRow.status == "live")
            )
            for row, tz_name in (await session.execute(stmt)).all():
                payload = row.payload or {}
                state = payload.get("current_state") or {}
                today_iso = _user_local_day_iso(tz_name)

                # Day rollover: state's day is before today.
                if state.get("day") and state.get("day") < today_iso:
                    out.append((row.id, row.user_id, "day_rollover"))
                    continue

                # Backstop: last_update_at is too old.
                lua = payload.get("last_update_at")
                if not lua:
                    out.append((row.id, row.user_id, "missing_state"))
                    continue
                try:
                    lua_dt = datetime.fromisoformat(lua.replace("Z", "+00:00"))
                    if lua_dt.tzinfo:
                        lua_dt = lua_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    if lua_dt < cutoff_naive:
                        out.append((row.id, row.user_id, "stale"))
                except Exception:
                    out.append((row.id, row.user_id, "unparseable_state"))
    except Exception:
        logger.exception("attention_sweep: list failed")
    return out


async def _poll_event_streams() -> int:
    """Run a poll cycle for every user with at least one live event_stream
    attention. Returns the count of users polled.

    We evaluate per-user (not per-attention) so a user's pollers run
    together and can share any session-level caching the poller layer adds
    later. Cursor management lives inside ``PollerSource`` — this function
    only triggers the cycle.
    """
    user_ids: set[str] = set()
    try:
        async with async_session() as session:
            stmt = (
                select(AttentionRow.user_id)
                .where(AttentionRow.status == "live")
                .where(AttentionRow.card == "event_stream")
            )
            for (uid,) in (await session.execute(stmt)).all():
                if uid:
                    user_ids.add(uid)
    except Exception:
        logger.exception("attention_sweep: event_stream user list failed")
        return 0

    n_polled = 0
    for uid in user_ids:
        try:
            updated = await evaluate_user_attentions(
                user_id=uid,
                card_filter=("event_stream",),
                trigger="sweep:event_stream_poll",
            )
            if updated:
                n_polled += 1
        except Exception:
            logger.exception(
                "attention_sweep: event_stream poll raised user=%s", uid[:8]
            )
    if n_polled:
        logger.info("attention_sweep: polled event_streams for %d users", n_polled)
    return n_polled


async def _tick() -> int:
    targets = await _stale_attentions()
    n_updated = 0
    for attention_id, _user_id, reason in targets:
        try:
            result = await evaluate_attention(
                attention_id=attention_id, trigger=f"sweep:{reason}"
            )
            if result is not None:
                n_updated += 1
        except Exception:
            logger.exception(
                "attention_sweep: eval raised id=%s reason=%s",
                attention_id[:8],
                reason,
            )
    if n_updated:
        logger.info("attention_sweep: re-evaluated %d attentions", n_updated)

    try:
        await _poll_event_streams()
    except Exception:
        logger.exception("attention_sweep: event_stream poll cycle raised")
    return n_updated


async def run_forever(*, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("attention_sweep: tick raised")
        await asyncio.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument("--once", action="store_true", help="Run one tick and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        n = asyncio.run(_tick())
        print(f"updated {n} attentions")
    else:
        asyncio.run(run_forever(poll_interval_s=args.poll))


if __name__ == "__main__":
    main()
