"""Manually fire run_bootstrap_async for a user.

Useful when:
  - Composio webhook didn't deliver (so the connection.created path
    never fired the bootstrap)
  - The async watcher task got killed by a uvicorn reload mid-poll
  - bootstrap_runs.last_status='failed' and you've fixed the underlying
    bug — this clears the failed marker and re-runs

Usage:
  python scripts/fire_bootstrap.py --user-id <uid>
  python scripts/fire_bootstrap.py --user-id <uid> --force   # bypass the
                                                             # 1-hour
                                                             # success
                                                             # dedupe
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from donna_runtime.env import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from api.composio_webhook import run_bootstrap_async  # noqa: E402
from backend.db.session import async_session  # noqa: E402
from db.models import User  # noqa: E402


async def _clear_bootstrap_runs(user_id: str) -> None:
    """Wipe bootstrap_runs so the dedupe / running-status guards don't
    block a fresh attempt."""
    async with async_session() as s:
        u = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is None:
            print(f"  no user with id={user_id}")
            return
        profile = dict(u.living_profile or {})
        if "bootstrap_runs" in profile:
            del profile["bootstrap_runs"]
            u.living_profile = profile
            flag_modified(u, "living_profile")
            await s.commit()
            print("  cleared bootstrap_runs")


async def main(user_id: str, force: bool) -> int:
    if force:
        await _clear_bootstrap_runs(user_id)
    print(f"firing bootstrap for user_id={user_id}...")
    res = await run_bootstrap_async(user_id)
    print(f"result: {res}")
    return 0 if res.get("status") in ("completed", "skipped") else 1


def cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-id", required=True)
    p.add_argument(
        "--force",
        action="store_true",
        help="Clear bootstrap_runs first so the dedupe / 'already running' "
             "guards don't block. Use after fixing a failed run.",
    )
    args = p.parse_args()
    return asyncio.run(main(args.user_id, args.force))


if __name__ == "__main__":
    sys.exit(cli())
