from __future__ import annotations

import argparse
import asyncio
import logging

from backend.memory.jobs.schedule_worker import run_forever


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--batch", type=int, default=25)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    await run_forever(poll_interval_s=args.poll, batch_size=args.batch)


if __name__ == "__main__":
    asyncio.run(main())

