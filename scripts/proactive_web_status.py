"""One-screen status for the proactive web search subsystem.

Usage:
    python scripts/proactive_web_status.py <user_id>
    python scripts/proactive_web_status.py <user_id> --drafts 20

Shows: active subscriptions, signal queue depth, recent shadow drafts,
and (when --exa is passed) live websets at Exa.

This is the operator command - run it anytime to see what Donna is
actually watching, what has come in, and what she's drafted.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import desc, func, select

from backend.db.session import async_session
from db.models import ChatMessage, ProactiveSignal, ProactiveSubscription


async def _print_subs(user_id: str) -> None:
    async with async_session() as s:
        rows = (
            await s.execute(
                select(ProactiveSubscription)
                .where(
                    ProactiveSubscription.user_id == user_id,
                    ProactiveSubscription.active.is_(True),
                )
                .order_by(ProactiveSubscription.created_at)
            )
        ).scalars().all()
    print(f"=== Active subscriptions ({len(rows)}) ===")
    for r in rows:
        if r.webset_id and r.monitor_id:
            flag = "OK  "
        elif r.webset_id:
            flag = "WS  "
        else:
            flag = "PEND"
        print(f"  [{flag}] {r.description[:75]}")
        print(f"         intent={r.intent_key}")
        if r.webset_id:
            print(f"         ws={r.webset_id}  mon={r.monitor_id}")
    print()


async def _print_queue(user_id: str) -> None:
    async with async_session() as s:
        pending = (
            await s.execute(
                select(func.count())
                .select_from(ProactiveSignal)
                .where(
                    ProactiveSignal.user_id == user_id,
                    ProactiveSignal.consumed_at.is_(None),
                )
            )
        ).scalar()
        consumed = (
            await s.execute(
                select(func.count())
                .select_from(ProactiveSignal)
                .where(
                    ProactiveSignal.user_id == user_id,
                    ProactiveSignal.consumed_at.isnot(None),
                )
            )
        ).scalar()
    print("=== Signal queue ===")
    print(f"  pending: {pending}    consumed: {consumed}")
    print()


async def _print_drafts(user_id: str, limit: int) -> None:
    async with async_session() as s:
        shadow_rows = (
            await s.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.is_proactive.is_(True),
                    ChatMessage.is_shadow.is_(True),
                )
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
            )
        ).scalars().all()
        live_rows = (
            await s.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.is_proactive.is_(True),
                    ChatMessage.is_shadow.is_(False),
                )
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
            )
        ).scalars().all()
    print(f"=== Shadow drafts ({len(shadow_rows)}) ===")
    for r in shadow_rows:
        print(f"  [{r.created_at.strftime('%m-%d %H:%M')}]  {r.content[:90]}")
    print()
    print(f"=== Live drafts (sent to WhatsApp) ({len(live_rows)}) ===")
    for r in live_rows:
        print(f"  [{r.created_at.strftime('%m-%d %H:%M')}]  {r.content[:90]}")
    print()


async def _print_exa(user_id: str) -> None:
    try:
        import httpx
    except ImportError:
        return
    key = os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        print("=== Exa websets (skipped: EXA_API_KEY not set) ===\n")
        return
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(
            "https://api.exa.ai/websets/v0/websets",
            headers={"x-api-key": key},
        )
        items = (r.json() or {}).get("data") or []
    print(f"=== Live websets at Exa ({len(items)}) ===")
    for w in items[:20]:
        search = (w.get("searches") or [{}])[0]
        q = (search.get("query") or "?")[:65]
        print(f"  [{w.get('status'):<8}] {w.get('id')}")
        print(f"             {q}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot of the proactive web search subsystem for one user.",
    )
    parser.add_argument("user_id", help="user_id to inspect")
    parser.add_argument(
        "--drafts", type=int, default=10, help="how many recent drafts to show"
    )
    parser.add_argument(
        "--exa", action="store_true", help="also list live websets at Exa"
    )
    args = parser.parse_args()

    print()
    await _print_subs(args.user_id)
    await _print_queue(args.user_id)
    await _print_drafts(args.user_id, args.drafts)
    if args.exa:
        await _print_exa(args.user_id)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    asyncio.run(main())
