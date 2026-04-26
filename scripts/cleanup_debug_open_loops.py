"""One-shot cleanup: archive open_loops whose content is debug residue.

Strings like ``vO7hjeAjmsdlGgUd`` slipped into the open_loops table
during testing. The compose-side noise filter hides them from the
dashboard, but they still bleed into ``/observe`` and any other
unfiltered surface. This script flips them to ``status='archived'``
with a ``resolved_at`` timestamp so they stop showing up everywhere.

Idempotent: re-running is a no-op once status is ``archived``.

Usage:
    python -m scripts.cleanup_debug_open_loops             # dry-run
    python -m scripts.cleanup_debug_open_loops --apply
    python -m scripts.cleanup_debug_open_loops --user <id> [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select, update

from db.models import OpenLoop
from db.session import async_session
from donna.attention.noise import (
    content_contains_debug_token,
    looks_like_debug_token,
)

logger = logging.getLogger(__name__)


def _is_debug_loop(loop: OpenLoop) -> bool:
    content = (loop.content or "").strip()
    if not content:
        return False
    if content_contains_debug_token(content):
        return True
    # Also catch the case where the WHOLE content is one big debug
    # token with no spaces at all.
    return looks_like_debug_token(content)


async def _list_active_loops(user_id: str | None) -> list[OpenLoop]:
    async with async_session() as session:
        stmt = (
            select(OpenLoop)
            .where(OpenLoop.status == "active")
            .order_by(OpenLoop.created_at.asc())
        )
        if user_id:
            stmt = stmt.where(OpenLoop.user_id == user_id)
        rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _archive_loops(loop_ids: list[str]) -> None:
    if not loop_ids:
        return
    async with async_session() as session:
        await session.execute(
            update(OpenLoop)
            .where(OpenLoop.id.in_(loop_ids))
            .values(
                status="archived",
                resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually mutate the DB (default is dry-run)",
    )
    parser.add_argument("--user", help="restrict to a single user_id")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )

    rows = await _list_active_loops(args.user)
    if not rows:
        print("no active open_loops found")
        return

    debug_rows = [r for r in rows if _is_debug_loop(r)]
    if not debug_rows:
        print(f"scanned {len(rows)} open_loop(s); nothing matched the debug filter")
        return

    for r in debug_rows:
        snippet = (r.content or "").strip()[:100]
        print(f"user={r.user_id[:8]} loop={r.id[:8]} content={snippet!r}")

    if not args.apply:
        print(
            f"\ndry-run: would archive {len(debug_rows)} debug-shape "
            f"open_loop(s). re-run with --apply to mutate."
        )
        return

    await _archive_loops([r.id for r in debug_rows])
    print(f"\narchived {len(debug_rows)} debug-shape open_loop(s).")


if __name__ == "__main__":
    asyncio.run(main())
