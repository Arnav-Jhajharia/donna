"""End-to-end smoke for Phase 3 bootstrap pipeline.

Bypasses the webhook (which expects pre-V3 Composio events) and drives
bootstrap directly. Flow:

  1. Upsert smoke user in Postgres
  2. Call connect_integration → print OAuth URL
  3. Wait for you to OAuth in browser
  4. Run all four bootstrap stages + biography synthesis
  5. Print row counts + render the BIOGRAPHY block

Usage:
  python scripts/smoke_p3.py --user-id smoke-p3 --products gmail
  python scripts/smoke_p3.py --user-id smoke-p3 --products gmail calendar
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

from backend.db.session import async_session  # noqa: E402
from backend.memory.tools.connect_integration import (  # noqa: E402
    connect_integration,
)
from backend.memory.user_facts.rendering import (  # noqa: E402
    render_living_profile_block,
)
from db.models import CalendarEntry, EmailMessage, User  # noqa: E402


async def _upsert_user(user_id: str) -> None:
    async with async_session() as s:
        existing = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if existing:
            print(f"user {user_id} exists (phone={existing.phone})")
            return
        s.add(User(id=user_id, phone=f"+smoke-{user_id}"))
        await s.commit()
        print(f"created user {user_id}")


async def _stage_connect(user_id: str, products: list[str]) -> None:
    print(f"\n── connect_integration({user_id}, google, {products}) ──")
    result = await connect_integration(
        user_id=user_id, provider="google", products=products
    )
    print(f"status: {result.get('status')}")
    if result.get("status") == "already_connected":
        print("integration already connected — skipping OAuth wait")
        return
    print(f"connection_id: {result.get('connection_id')}")
    print(f"\nOAUTH URL:\n  {result.get('url')}\n")
    print(result.get("message"))
    print("\n=> open that url, complete the google consent, then come back here")
    input("\npress Enter once OAuth is done > ")


async def _stage_bootstrap(user_id: str) -> None:
    print(f"\n── run_bootstrap_async({user_id}) ──")
    from api.composio_webhook import run_bootstrap_async

    await run_bootstrap_async(user_id)


async def _stage_report(user_id: str) -> None:
    print(f"\n── results for {user_id} ──")
    async with async_session() as s:
        emails = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.user_id == user_id)
            )
        ).scalars().all()
        events = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == user_id)
            )
        ).scalars().all()
        user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one()

    print(f"email_messages: {len(emails)}")
    by_depth: dict[str, int] = {}
    for e in emails:
        by_depth[e.ingest_depth] = by_depth.get(e.ingest_depth, 0) + 1
    for d, n in sorted(by_depth.items()):
        print(f"  - {d}: {n}")
    print(f"calendar_entries: {len(events)}")

    bio = (user.living_profile or {}).get("biography")
    if not bio:
        print("\nbiography: <not populated> — synthesis may have failed")
        return
    overview = bio.get("overview") or "(empty)"
    print(f"\nbiography.overview: {overview}")
    rendered = render_living_profile_block(user.living_profile)
    print("\n── rendered system-prompt block ──")
    print(rendered or "(empty)")


async def _amain(
    user_id: str, products: list[str], bootstrap_only: bool
) -> int:
    if bootstrap_only:
        await _stage_bootstrap(user_id)
        await _stage_report(user_id)
        return 0
    await _upsert_user(user_id)
    await _stage_connect(user_id, products)
    await _stage_bootstrap(user_id)
    await _stage_report(user_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="smoke-p3")
    parser.add_argument(
        "--products",
        nargs="+",
        choices=["gmail", "calendar"],
        default=["gmail"],
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Skip user-create and connect; only run bootstrap + report. "
        "Use after OAuthing through Donna in chat_donna.py.",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args.user_id, args.products, args.bootstrap_only))


if __name__ == "__main__":
    sys.exit(main())
