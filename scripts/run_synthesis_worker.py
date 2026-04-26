"""Standalone Living Profile synthesis worker.

Entry point for the dedicated synthesis deployment (Railway service or
local terminal). Polls active users, runs nightly full synthesis at
local 02:00 and morning digest refresh at local 05:00.

Launched by ``bin/start.sh`` when ``DONNA_PROCESS_ROLE=synthesis``. The
API service must NOT spawn this same task — see ``api/main.py`` for
the role gate.

When ``PORT`` is set, also serves a tiny ``/health`` HTTP endpoint so
Railway's default healthcheck passes.
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

from backend.memory.jobs.synthesis_worker import (
    DEFAULT_POLL_INTERVAL_S,
    run_forever,
)
from db.migrations import create_tables

logger = logging.getLogger(__name__)


async def _serve_health(port: int) -> None:
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok", "role": "synthesis"}

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
        description="Donna Living Profile synthesis worker.",
    )
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL_S)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("synthesis worker starting (poll=%.1fs)", args.poll)

    try:
        await create_tables()
    except Exception:
        logger.exception(
            "synthesis: create_tables failed (DB unreachable?) — continuing"
        )

    port_raw = os.environ.get("PORT")
    if port_raw:
        try:
            port = int(port_raw)
            asyncio.create_task(_serve_health(port), name="health")
            logger.info("synthesis: /health on :%d", port)
        except ValueError:
            logger.warning(
                "synthesis: PORT=%r is not an int — skipping health", port_raw
            )

    await run_forever(poll_interval_s=args.poll)


if __name__ == "__main__":
    asyncio.run(main())
