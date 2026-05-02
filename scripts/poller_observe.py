"""Live observability into the proactive poller.

One screen showing:
  1. Worker process status (local PID check + Railway notes)
  2. Active subscriptions with due/not-due cadence math
  3. Recent enqueued signals (last 24h, with query attribution)
  4. Signal queue depth (pending vs consumed)
  5. Recent shadow / live drafts
  6. Estimated credit burn this month

Flags:
  --watch [N]       refresh every N seconds (default 30) — live tail mode
  --force-poll      trigger one poll right now (writes real signals,
                    costs ~10 credits per due sub)
  --user <id>       restrict to one user (default: all users)

Usage:
    python scripts/poller_observe.py
    python scripts/poller_observe.py --user 986cbc94-...
    python scripts/poller_observe.py --watch 60
    python scripts/poller_observe.py --force-poll --user 986cbc94-...
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import desc, func, select

from backend.db.session import async_session
from backend.web.proactive.poller import _CADENCE_TO_INTERVAL, _is_due
from db.models import ChatMessage, ProactiveSignal, ProactiveSubscription


# Cost model — keep in sync with system_b/fetcher.py defaults.
CREDITS_PER_SEARCH = 5
CREDITS_PER_FIND_SIMILAR = 5


def _hr() -> None:
    print("─" * 78)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _human_delta(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 0:
        return f"{_human_delta(-td)} ago"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600}h"


def _human_age(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "never"
    return f"{_human_delta(now - then)} ago"


# -- Section 1: worker process ---------------------------------------------


def _check_worker_process() -> dict:
    """Find local proactive worker process if any."""
    try:
        result = subprocess.run(
            ["pgrep", "-fla", "run_proactive_worker.py"],
            capture_output=True, text=True, timeout=2,
        )
        lines = [
            l.strip() for l in result.stdout.splitlines() if l.strip()
        ]
        return {"running": bool(lines), "pids": lines}
    except Exception:
        return {"running": False, "pids": []}


def _print_worker_status() -> None:
    _hr()
    print("1. WORKER STATUS")
    _hr()
    info = _check_worker_process()
    if info["running"]:
        print(f"  local process: RUNNING")
        for pid_line in info["pids"][:3]:
            print(f"    {pid_line}")
    else:
        print("  local process: not running")
    paused = os.environ.get("DONNA_EXA_AUTOMATION_PAUSE", "")
    print(f"  local cost gate (DONNA_EXA_AUTOMATION_PAUSE): {paused or 'unset'}")
    print("  Railway: check `railway logs -s donna-proactive` for live tail")
    print()


# -- Section 2: active subs with due/not-due -------------------------------


async def _print_subs(user_filter: str | None) -> int:
    """Returns number of subs that are currently due."""
    _hr()
    print("2. ACTIVE SUBSCRIPTIONS")
    _hr()
    now = _utcnow()
    async with async_session() as s:
        stmt = (
            select(ProactiveSubscription)
            .where(ProactiveSubscription.active.is_(True))
            .order_by(ProactiveSubscription.last_hit_at.asc().nulls_first())
        )
        if user_filter:
            stmt = stmt.where(ProactiveSubscription.user_id == user_filter)
        rows = (await s.execute(stmt)).scalars().all()

    if not rows:
        print("  (none)")
        print()
        return 0

    print(f"  {'cadence':<8}  {'last poll':<13}  {'due in':<13}  description")
    print(f"  {'-' * 8}  {'-' * 13}  {'-' * 13}  {'-' * 50}")
    due_count = 0
    for sub in rows:
        cadence = sub.cadence or "weekly"
        last = _human_age(sub.last_hit_at, now)
        if _is_due(sub, now):
            due_count += 1
            interval = _CADENCE_TO_INTERVAL.get(
                cadence, _CADENCE_TO_INTERVAL["weekly"]
            )
            if sub.last_hit_at is None:
                due_label = "DUE NOW"
            else:
                overdue = (now - sub.last_hit_at) - interval
                due_label = "DUE NOW" if overdue.total_seconds() < 60 else f"DUE +{_human_delta(overdue)}"
        else:
            interval = _CADENCE_TO_INTERVAL.get(
                cadence, _CADENCE_TO_INTERVAL["weekly"]
            )
            remaining = (sub.last_hit_at + interval) - now if sub.last_hit_at else timedelta(0)
            due_label = f"in {_human_delta(remaining)}"
        print(
            f"  {cadence:<8}  {last:<13}  {due_label:<13}  "
            f"{sub.description[:55]}"
        )
    print()
    print(f"  {due_count}/{len(rows)} due now")
    print()
    return due_count


# -- Section 3: recent enqueued signals ------------------------------------


async def _print_recent_signals(user_filter: str | None) -> None:
    _hr()
    print("3. RECENT ENQUEUED SIGNALS (last 24h)")
    _hr()
    cutoff = _utcnow() - timedelta(hours=24)
    async with async_session() as s:
        stmt = (
            select(ProactiveSignal, ProactiveSubscription)
            .join(
                ProactiveSubscription,
                ProactiveSignal.subscription_id == ProactiveSubscription.id,
            )
            .where(ProactiveSignal.arrived_at >= cutoff)
            .order_by(desc(ProactiveSignal.arrived_at))
            .limit(15)
        )
        if user_filter:
            stmt = stmt.where(ProactiveSignal.user_id == user_filter)
        rows = (await s.execute(stmt)).all()

    if not rows:
        print("  (none in last 24h)")
        print()
        return

    now = _utcnow()
    for sig, sub in rows:
        age = _human_age(sig.arrived_at, now)
        payload = sig.payload or {}
        title = (payload.get("title") or "?")[:65]
        via_sim = " [+sim]" if payload.get("system_b_via_similar") else ""
        consumed = " ✓judged" if sig.consumed_at else " ⏳pending"
        print(f"  {age:<13}  {title}{via_sim}{consumed}")
        print(f"                 sub: {sub.description[:60]}")
    print()


# -- Section 4: signal queue ----------------------------------------------


async def _print_queue(user_filter: str | None) -> None:
    _hr()
    print("4. SIGNAL QUEUE")
    _hr()
    async with async_session() as s:
        pending_stmt = select(func.count()).select_from(ProactiveSignal).where(
            ProactiveSignal.consumed_at.is_(None)
        )
        consumed_24h_stmt = select(func.count()).select_from(ProactiveSignal).where(
            ProactiveSignal.consumed_at.isnot(None),
            ProactiveSignal.consumed_at >= _utcnow() - timedelta(hours=24),
        )
        if user_filter:
            pending_stmt = pending_stmt.where(
                ProactiveSignal.user_id == user_filter
            )
            consumed_24h_stmt = consumed_24h_stmt.where(
                ProactiveSignal.user_id == user_filter
            )
        pending = (await s.execute(pending_stmt)).scalar() or 0
        consumed_24h = (await s.execute(consumed_24h_stmt)).scalar() or 0

    print(f"  pending (waiting for drain):  {pending}")
    print(f"  consumed in last 24h:         {consumed_24h}")
    print()


# -- Section 5: recent drafts ----------------------------------------------


async def _print_drafts(user_filter: str | None) -> None:
    _hr()
    print("5. RECENT DRAFTS (shadow + live)")
    _hr()
    async with async_session() as s:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.is_proactive.is_(True))
            .order_by(desc(ChatMessage.created_at))
            .limit(8)
        )
        if user_filter:
            stmt = stmt.where(ChatMessage.user_id == user_filter)
        rows = (await s.execute(stmt)).scalars().all()

    if not rows:
        print("  (no proactive drafts yet)")
        print()
        return

    now = _utcnow()
    for r in rows:
        age = _human_age(r.created_at, now)
        mode = "shadow" if r.is_shadow else "LIVE"
        print(f"  [{age:<13}|{mode:<6}] {r.content[:75]}")
    print()


# -- Section 6: cost estimate ----------------------------------------------


async def _print_cost(user_filter: str | None) -> None:
    _hr()
    print("6. COST ESTIMATE (this calendar month)")
    _hr()
    # Approximate: count signals this month, divide by avg per-fetch yield
    # to back out fetches. Each fetch = 1 /search + 1 /findSimilar = 10 credits.
    # Rough yield assumption: ~6 deduped signals per fetch (3 from search + 3
    # from findSimilar, with within-batch dedup keeping most).
    month_start = _utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as s:
        stmt = select(func.count()).select_from(ProactiveSignal).where(
            ProactiveSignal.arrived_at >= month_start
        )
        if user_filter:
            stmt = stmt.where(ProactiveSignal.user_id == user_filter)
        signals = (await s.execute(stmt)).scalar() or 0
    inferred_fetches = max(1, signals // 6) if signals else 0
    inferred_credits = inferred_fetches * (
        CREDITS_PER_SEARCH + CREDITS_PER_FIND_SIMILAR
    )
    pct = (inferred_credits / 8000) * 100
    print(f"  signals enqueued this month:  {signals}")
    print(f"  inferred fetch cycles:        ~{inferred_fetches}")
    print(f"  inferred credits used:        ~{inferred_credits} (~{pct:.1f}% of $49 budget)")
    print()


# -- Section 7: force-poll -------------------------------------------------


async def _force_poll(user_filter: str | None) -> None:
    _hr()
    print("FORCING ONE POLL CYCLE")
    _hr()
    if user_filter:
        users = [user_filter]
    else:
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(ProactiveSubscription.user_id).where(
                        ProactiveSubscription.active.is_(True)
                    ).distinct()
                )
            ).all()
            users = [r[0] for r in rows]
    if not users:
        print("  no users with active subs")
        return

    from backend.web.proactive.poller import poll_pending_subscriptions
    for uid in users:
        summary = await poll_pending_subscriptions(uid)
        print(
            f"  user={uid[:8]}  polled={summary.polled}  "
            f"new={summary.new_signals}  failed={summary.failed}"
        )
    print()


# -- main ------------------------------------------------------------------


async def render(user_filter: str | None) -> None:
    print()
    print(f"PROACTIVE POLLER — LIVE VIEW   {_utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    if user_filter:
        print(f"user: {user_filter}")
    print()
    _print_worker_status()
    await _print_subs(user_filter)
    await _print_recent_signals(user_filter)
    await _print_queue(user_filter)
    await _print_drafts(user_filter)
    await _print_cost(user_filter)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=None, help="restrict to one user_id")
    parser.add_argument(
        "--watch", type=int, default=0,
        help="re-run every N seconds (live tail; 0 = single shot)",
    )
    parser.add_argument(
        "--force-poll", action="store_true",
        help="trigger one poll cycle now (REAL fetch, costs credits)",
    )
    args = parser.parse_args()

    if args.force_poll:
        await _force_poll(args.user)
        return

    if args.watch > 0:
        try:
            while True:
                # Clear screen for live view.
                print("\033[2J\033[H", end="")
                await render(args.user)
                print(f"  refreshing in {args.watch}s — Ctrl+C to exit")
                await asyncio.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n  watch mode stopped.")
    else:
        await render(args.user)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
