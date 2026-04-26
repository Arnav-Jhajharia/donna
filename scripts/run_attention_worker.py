"""Standalone proactive attention worker.

Entry point for the dedicated attention deployment (Railway service or
local terminal). Two clocks running side-by-side:

- propose pass every 30 min: each active user's proposers run to
  author SHADOW attentions
- promote pass every 15 min: ticks every SHADOW row, promotes to
  OFFERED or quietly archives

Launched by ``bin/start.sh`` when ``DONNA_PROCESS_ROLE=attention``. The
API service must NOT spawn this same task — see ``api/main.py`` for
the role gate.

When ``PORT`` is set, serves a tiny ``/health`` endpoint for Railway.
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

from backend.memory.jobs.attention_worker import (
    DEFAULT_POLL_INTERVAL_S,
    PROMOTE_INTERVAL_SEC,
    PROPOSE_INTERVAL_SEC,
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
        return {"status": "ok", "role": "attention"}

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
        description="Donna proactive attention worker (propose + promote).",
    )
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument(
        "--propose-interval", type=float, default=PROPOSE_INTERVAL_SEC
    )
    parser.add_argument(
        "--promote-interval", type=float, default=PROMOTE_INTERVAL_SEC
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "attention worker starting (poll=%.1fs, propose=%.0fs, promote=%.0fs)",
        args.poll,
        args.propose_interval,
        args.promote_interval,
    )

    try:
        await create_tables()
    except Exception:
        logger.exception(
            "attention: create_tables failed (DB unreachable?) — continuing"
        )

    port_raw = os.environ.get("PORT")
    if port_raw:
        try:
            port = int(port_raw)
            asyncio.create_task(_serve_health(port), name="health")
            logger.info("attention: /health on :%d", port)
        except ValueError:
            logger.warning(
                "attention: PORT=%r is not an int — skipping health", port_raw
            )

    await run_forever(
        poll_interval_s=args.poll,
        propose_interval_s=args.propose_interval,
        promote_interval_s=args.promote_interval,
    )


if __name__ == "__main__":
    asyncio.run(main())
