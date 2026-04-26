"""Print recent proactive activity for one user against the live DB.

    python scripts/proactive_status.py <user_id>
    python scripts/proactive_status.py <user_id> --hours 48

Reads from the database configured by the project's ``config.settings``
(via ``backend.db.session.async_session``). No mocking, no stubbing.
Use this to peek at what Donna actually did proactively in the last
window — fires, suppressions, held notes, queued schedules, sent chats.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from backend.db.session import async_session
from db.models import (
    ChatMessage,
    DonnaSchedule,
    PendingProactiveNote,
    ProactivePing,
)


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.replace(microsecond=0).isoformat(sep=" ")


def _fmt_age(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "?"
    delta = now - value
    if delta.total_seconds() < 0:
        return f"in {-int(delta.total_seconds() // 60)}m"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)}h ago"
    return f"{delta.days}d ago"


def _section(title: str) -> None:
    print()
    print(f"== {title}")
    print()


async def _print_pings(user_id: str, since: datetime, now: datetime) -> None:
    async with async_session() as s:
        rows = (
            await s.execute(
                select(ProactivePing)
                .where(ProactivePing.user_id == user_id)
                .where(ProactivePing.fired_at >= since)
                .order_by(ProactivePing.fired_at.desc())
            )
        ).scalars().all()

    fired = [r for r in rows if r.suppressed_reason is None]
    suppressed = [r for r in rows if r.suppressed_reason is not None]

    _section(f"PROACTIVE PINGS — fired ({len(fired)}) | suppressed ({len(suppressed)})")
    if not rows:
        print("(none)")
        return
    for r in rows:
        marker = "FIRED " if r.suppressed_reason is None else "SUPPR "
        topic = r.topic_key or "-"
        msg_ref = r.message_ref or "-"
        why = r.suppressed_reason or "ok"
        print(
            f"{marker} {_fmt_ts(r.fired_at)}  "
            f"src={r.source:<14}  topic={topic[:24]:<24}  "
            f"ref={msg_ref[:24]:<24}  why={why}"
        )


async def _print_pending(user_id: str, now: datetime) -> None:
    async with async_session() as s:
        rows = (
            await s.execute(
                select(PendingProactiveNote)
                .where(PendingProactiveNote.user_id == user_id)
                .where(PendingProactiveNote.status == "pending")
                .order_by(PendingProactiveNote.created_at.desc())
            )
        ).scalars().all()

    _section(f"PENDING NOTES (hold lane) — pending ({len(rows)})")
    if not rows:
        print("(none)")
        return
    for r in rows:
        topic = r.topic_key or "-"
        expires = _fmt_age(r.expires_at, now)
        print(
            f"  {_fmt_ts(r.created_at)}  "
            f"src={r.source:<14}  topic={topic[:24]:<24}  "
            f"expires={expires}"
        )
        print(f"    draft: {r.draft[:100]}")
        if r.reasoning:
            print(f"    why:   {r.reasoning[:100]}")


async def _print_schedules(user_id: str, ahead: timedelta, now: datetime) -> None:
    until = now + ahead
    async with async_session() as s:
        rows = (
            await s.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.user_id == user_id)
                .where(DonnaSchedule.fired.is_(False))
                .where(DonnaSchedule.fire_at <= until)
                .order_by(DonnaSchedule.fire_at.asc())
            )
        ).scalars().all()

    _section(f"QUEUED SCHEDULES — next {int(ahead.total_seconds() // 3600)}h ({len(rows)})")
    if not rows:
        print("(none)")
        return
    for r in rows:
        body = ""
        ctx = r.context or {}
        msgs = ctx.get("messages") if isinstance(ctx, dict) else None
        if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
            body = str(msgs[0].get("body") or "")[:80]
        attn = (r.attention_id or "-")[:24]
        when_in = _fmt_age(r.fire_at, now)
        print(
            f"  {_fmt_ts(r.fire_at)} ({when_in:>10})  "
            f"origin={r.origin:<6}  status={r.status:<8}  "
            f"attention={attn:<24}"
        )
        if body:
            print(f"    body:  {body}")


async def _print_recent_proactive_chats(
    user_id: str, since: datetime, now: datetime
) -> None:
    async with async_session() as s:
        rows = (
            await s.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .where(ChatMessage.role == "assistant")
                .where(ChatMessage.is_proactive.is_(True))
                .where(ChatMessage.created_at >= since)
                .order_by(ChatMessage.created_at.desc())
            )
        ).scalars().all()

    _section(f"PROACTIVE CHAT MESSAGES SENT ({len(rows)})")
    if not rows:
        print("(none)")
        return
    for r in rows:
        print(f"  {_fmt_ts(r.created_at)}  {(r.content or '')[:120]}")


async def main(user_id: str, hours: int) -> None:
    now = datetime.utcnow()
    since = now - timedelta(hours=hours)
    print(f"user_id   = {user_id}")
    print(f"window    = last {hours}h (since {_fmt_ts(since)} UTC)")
    print(f"now       = {_fmt_ts(now)} UTC")
    await _print_pings(user_id, since, now)
    await _print_pending(user_id, now)
    await _print_schedules(user_id, timedelta(hours=24), now)
    await _print_recent_proactive_chats(user_id, since, now)
    print()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Print recent proactive activity for one user."
    )
    p.add_argument("user_id", help="User id to inspect.")
    p.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Lookback window in hours (default 24).",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.user_id, args.hours))
