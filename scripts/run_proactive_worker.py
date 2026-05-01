"""Standalone proactive web search worker.

Entry point for the dedicated `donna-proactive` Railway service. Two
clocks running side-by-side:

- drain pass: every DONNA_PROACTIVE_DRAIN_S (default 600s = 10min) per
  active user. The drain trigger early-exits when the queue is empty,
  so this is cheap. Limits make sure we never burn through Exa credits
  on a hot user.
- ledger purge: once per hour, GC ledger rows older than 48h.

Launched by ``bin/start.sh`` when ``DONNA_PROCESS_ROLE=proactive``. The
API service must NOT spawn this same task - see ``api/main.py`` for
the role gate.

When ``PORT`` is set, serves a tiny ``/health`` endpoint for Railway.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select

from backend.web.proactive.store import PostgresDedupStore
from backend.web.proactive.triggers.drain import maybe_drain_signals
from db.migrations import create_tables
from db.models import User
from db.session import async_session

logger = logging.getLogger(__name__)


DEFAULT_DRAIN_INTERVAL_S = 600.0
DEFAULT_PURGE_INTERVAL_S = 3600.0
DEFAULT_POLL_INTERVAL_S = 21600.0  # 6h - free-tier fallback for unprovisioned subs


def _delivery_mode_for(profile: dict) -> str:
    raw = (profile or {}).get("proactive_delivery_mode") or "shadow"
    return raw if raw in {"shadow", "live", "none"} else "shadow"


async def _list_active_user_ids() -> list[tuple[str, dict]]:
    """Read users with active proactive subs. Returns (user_id, profile) pairs."""
    from db.models import ProactiveSubscription

    async with async_session() as session:
        rows = (
            await session.execute(
                select(User.id, User.living_profile).distinct().join(
                    ProactiveSubscription,
                    ProactiveSubscription.user_id == User.id,
                ).where(
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).all()
    return [(r[0], dict(r[1] or {})) for r in rows]


async def _drain_loop(interval: float) -> None:
    while True:
        try:
            users = await _list_active_user_ids()
            random.shuffle(users)
            for user_id, profile in users:
                mode = _delivery_mode_for(profile)
                try:
                    decision = await maybe_drain_signals(
                        user_id=user_id, delivery_mode=mode
                    )
                    if decision.signals_drained:
                        logger.info(
                            "drain user=%s drained=%d emitted=%d delivered=%d mode=%s",
                            user_id[:8],
                            decision.signals_drained,
                            decision.moves_emitted,
                            decision.drafts_delivered,
                            mode,
                        )
                except Exception:
                    logger.exception(
                        "drain failed user=%s", user_id[:8] if user_id else "?"
                    )
        except Exception:
            logger.exception("drain loop top-level error")

        await asyncio.sleep(interval)


async def _purge_loop(interval: float) -> None:
    store = PostgresDedupStore()
    while True:
        try:
            removed = await store.purge_older_than(hours=48)
            if removed:
                logger.info("ledger purge: removed=%d", removed)
        except Exception:
            logger.exception("purge loop error")
        await asyncio.sleep(interval)


async def _poll_loop(interval: float) -> None:
    """Free-tier fallback: poll exa_search for any sub without a
    webset_id. Runs alongside drain. When the user upgrades to a
    websets-capable plan, provisioned subs skip this loop automatically.
    """
    from backend.web.proactive.poller import poll_pending_subscriptions

    while True:
        try:
            users = await _list_active_user_ids()
            for user_id, _profile in users:
                try:
                    summary = await poll_pending_subscriptions(user_id)
                    if summary.polled or summary.new_signals or summary.failed:
                        logger.info(
                            "poll user=%s polled=%d new=%d failed=%d",
                            user_id[:8],
                            summary.polled,
                            summary.new_signals,
                            summary.failed,
                        )
                except Exception:
                    logger.exception(
                        "poll failed user=%s", user_id[:8] if user_id else "?"
                    )
        except Exception:
            logger.exception("poll loop top-level error")
        await asyncio.sleep(interval)


async def _serve_health(port: int) -> None:
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok", "role": "proactive"}

    config = uvicorn.Config(
        app, host="0.0.0.0", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Donna proactive web search worker (drain + purge).",
    )
    parser.add_argument(
        "--drain-interval",
        type=float,
        default=float(
            os.environ.get("DONNA_PROACTIVE_DRAIN_S") or DEFAULT_DRAIN_INTERVAL_S
        ),
    )
    parser.add_argument(
        "--purge-interval",
        type=float,
        default=float(
            os.environ.get("DONNA_PROACTIVE_PURGE_S") or DEFAULT_PURGE_INTERVAL_S
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(
            os.environ.get("DONNA_PROACTIVE_POLL_S") or DEFAULT_POLL_INTERVAL_S
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "proactive worker starting (drain=%.0fs, purge=%.0fs, poll=%.0fs)",
        args.drain_interval,
        args.purge_interval,
        args.poll_interval,
    )

    try:
        await create_tables()
    except Exception:
        logger.exception(
            "proactive: create_tables failed (DB unreachable?) - continuing"
        )

    tasks = [
        asyncio.create_task(_drain_loop(args.drain_interval)),
        asyncio.create_task(_purge_loop(args.purge_interval)),
        asyncio.create_task(_poll_loop(args.poll_interval)),
    ]
    port_raw = os.environ.get("PORT")
    if port_raw:
        try:
            tasks.append(asyncio.create_task(_serve_health(int(port_raw))))
        except ValueError:
            pass

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
