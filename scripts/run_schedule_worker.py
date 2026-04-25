"""Standalone reminder firing worker.

Entry point for the dedicated reminders deployment (Railway service or
local second terminal). Polls the DB, locks due rows, sends via WhatsApp,
and persists each fired reminder back into chat_messages so the next
BRAIN turn knows what Donna said while the user was away.

The same script is launched by ``bin/start.sh`` when
``DONNA_PROCESS_ROLE=reminders``. It is no longer co-spawned inside the
API process — the API service must NOT set ``DONNA_PROCESS_ROLE=reminders``.

When the ``PORT`` env var is set (Railway always sets this), the worker
also serves a tiny ``/health`` HTTP endpoint on that port so Railway's
default healthcheck passes without per-service dashboard tweaks.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from backend.memory.jobs.schedule_worker import run_forever
from db.migrations import create_tables

logger = logging.getLogger(__name__)


async def _serve_health(port: int) -> None:
    """Tiny liveness server so Railway's HTTP healthcheck passes.

    Liveness only — does NOT verify DB connectivity. Healthchecks that
    poke the DB cause restart loops on transient blips, which is worse
    than not having them.
    """
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok", "role": "reminders"}

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Donna reminder worker — fires DonnaSchedule rows.",
    )
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--batch", type=int, default=25)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "reminders worker starting (poll=%.1fs, batch=%d)", args.poll, args.batch
    )

    try:
        await create_tables()
    except Exception:
        logger.exception(
            "reminders: create_tables failed (DB unreachable?) — continuing"
        )

    port_raw = os.environ.get("PORT")
    if port_raw:
        try:
            port = int(port_raw)
            asyncio.create_task(_serve_health(port), name="health")
            logger.info("reminders: /health on :%d", port)
        except ValueError:
            logger.warning("reminders: PORT=%r is not an int — skipping health", port_raw)

    await run_forever(poll_interval_s=args.poll, batch_size=args.batch)


if __name__ == "__main__":
    asyncio.run(main())

