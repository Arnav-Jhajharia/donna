"""Read-only audit of donna-attention worker output.

Two queries against the prod DB:

1. Per-user (arnav by default): every shadow_inferred attention authored
   by the proposer/promoter loop, with status + age.
2. Cross-user (last 7 days): are the proposers producing output for
   anyone? If this returns 0 rows, the worker is either dead or all
   three proposers are structurally silent.

Run:
    python scripts/check_attention_health.py
    python scripts/check_attention_health.py --user-id <uuid>
    python scripts/check_attention_health.py --days 14
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import func, select

from db.models import AttentionRow, AttentionTickRow
from db.session import async_session

DEFAULT_USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"  # arnav


def _age(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    if delta.days >= 1:
        return f"{delta.days}d ago"
    h = delta.seconds // 3600
    if h >= 1:
        return f"{h}h ago"
    return f"{delta.seconds // 60}m ago"


async def per_user_audit(user_id: str) -> None:
    print(f"\n=== shadow_inferred attentions for user {user_id[:8]}... ===")
    async with async_session() as session:
        rows = (
            await session.execute(
                select(AttentionRow)
                .where(AttentionRow.user_id == user_id)
                .where(AttentionRow.origin.in_(["shadow_inferred", "offer_accepted"]))
                .order_by(AttentionRow.created_at.desc())
            )
        ).scalars().all()

    if not rows:
        print("  (zero rows — worker has never proposed anything for this user)")
        return

    print(f"  {len(rows)} rows total\n")
    print(f"  {'status':<20} {'origin':<18} {'card':<12} {'age':<10} title")
    print(f"  {'-'*20} {'-'*18} {'-'*12} {'-'*10} {'-'*40}")
    for r in rows:
        title = (r.title or "")[:50]
        print(
            f"  {r.status:<20} {r.origin:<18} {r.card:<12} "
            f"{_age(r.created_at):<10} {title}"
        )

    status_breakdown: dict[str, int] = {}
    for r in rows:
        status_breakdown[r.status] = status_breakdown.get(r.status, 0) + 1
    print(f"\n  by status: {status_breakdown}")


async def all_user_audit(days: int) -> None:
    print(f"\n=== cross-user proposer activity, last {days} days ===")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(AttentionRow)
                .where(AttentionRow.origin == "shadow_inferred")
                .where(AttentionRow.created_at >= cutoff.replace(tzinfo=None))
            )
        ).scalar_one()

        by_status = (
            await session.execute(
                select(AttentionRow.status, func.count())
                .where(AttentionRow.origin == "shadow_inferred")
                .where(AttentionRow.created_at >= cutoff.replace(tzinfo=None))
                .group_by(AttentionRow.status)
            )
        ).all()

        unique_users = (
            await session.execute(
                select(func.count(func.distinct(AttentionRow.user_id)))
                .where(AttentionRow.origin == "shadow_inferred")
                .where(AttentionRow.created_at >= cutoff.replace(tzinfo=None))
            )
        ).scalar_one()

    print(f"  total shadows authored: {total}")
    print(f"  unique users covered:   {unique_users}")
    print(f"  by status: {dict(by_status)}")

    if total == 0:
        print(
            "\n  ⚠ ZERO output for ANYONE in the window. "
            "Either the worker is down, or all three proposers are "
            "structurally silent (EntityMentionProposer is a stub; "
            "CalendarRecurrenceProposer needs recurring meetings; "
            "ChatPhraseProposer needs the canonical drinking pattern)."
        )


async def liveness_proxy(user_id: str) -> None:
    print(f"\n=== liveness proxy: most recent worker tick visible to user {user_id[:8]}... ===")
    async with async_session() as session:
        latest = (
            await session.execute(
                select(AttentionTickRow.at)
                .join(AttentionRow, AttentionTickRow.attention_id == AttentionRow.id)
                .where(AttentionRow.user_id == user_id)
                .order_by(AttentionTickRow.at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if latest is None:
        print("  no AttentionTickRow rows for this user — worker has never ticked their attentions")
    else:
        print(f"  latest tick: {latest.isoformat()} ({_age(latest)})")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    await per_user_audit(args.user_id)
    await liveness_proxy(args.user_id)
    await all_user_audit(args.days)


if __name__ == "__main__":
    asyncio.run(main())
