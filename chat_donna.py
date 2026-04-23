"""Interactive REPL for chatting with Donna as a fresh user.

Usage:
    python chat_donna.py                   # fresh timestamped user
    python chat_donna.py --user-id alice   # resume an existing user
    python chat_donna.py --phone +1555...  # pin a phone number on the user

Type /quit or Ctrl-D to exit. Type /trace to print the last turn's trace.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import User
from db.session import async_session
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.runner import donna_turn
from donna_runtime.tracing import TurnTrace


async def _ensure_user(user_id: str, phone: str | None) -> None:
    async with async_session() as session:
        existing = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            User(
                id=user_id,
                phone=phone or f"+repl-{user_id}",
                timezone="Asia/Singapore",
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        await session.commit()


def _print_burst(trace: TurnTrace) -> None:
    """Render send_burst bodies as WhatsApp-ish bubbles."""
    any_printed = False
    for call in trace.to_dict().get("tool_calls", []):
        tool = call.get("tool") or call.get("name") or ""
        if tool.endswith("send_burst"):
            messages = call.get("inputs", {}).get("messages", [])
            for m in messages:
                if isinstance(m, str):
                    print(f"  donna │ {m}")
                    any_printed = True
                elif isinstance(m, dict):
                    t = m.get("type", "text")
                    body = m.get("body") or m.get("caption") or ""
                    if t == "text" and body:
                        print(f"  donna │ {body}")
                        any_printed = True
                    elif t == "cta" and body:
                        labels = " | ".join(
                            b.get("title", "") for b in m.get("buttons", [])
                        )
                        print(f"  donna │ {body}")
                        print(f"        │ [{labels}]")
                        any_printed = True
                    elif t == "cta_url" and body:
                        print(f"  donna │ {body}")
                        print(f"        │ [{m.get('display_text', 'open')}: {m.get('url', '')}]")
                        any_printed = True
                    elif t == "image":
                        print(f"  donna │ [image: {m.get('url', '')}] {body}")
                        any_printed = True
                    elif t == "delay":
                        pass
        elif tool.endswith("stay_silent"):
            reason = call.get("inputs", {}).get("reason", "")
            print(f"  donna │ (silent: {reason})")
            any_printed = True
    if not any_printed:
        print("  donna │ (no terminator fired — possible loop bug)")


def _print_tool_trace(trace: TurnTrace) -> None:
    for call in trace.to_dict().get("tool_calls", []):
        tool = call.get("tool") or call.get("name") or ""
        short_name = tool.split("__")[-1] if tool else "?"
        inputs = json.dumps(call.get("inputs", {}), default=str)
        if len(inputs) > 120:
            inputs = inputs[:120] + "…"
        print(f"        · {short_name}({inputs})")


async def repl(user_id: str, phone: str | None, show_tools: bool) -> None:
    await _ensure_user(user_id, phone)
    print(f"donna chat · user_id={user_id}")
    print("type /quit to exit, /trace for the last trace, /tools to toggle tool echo\n")

    config = DonnaAgentConfig(user_id=user_id)
    last_trace: TurnTrace | None = None

    while True:
        try:
            line = input("you  │ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return
        if line == "/trace":
            if last_trace is None:
                print("  (no turn yet)")
            else:
                print(json.dumps(last_trace.to_dict(), indent=2, default=str))
            continue
        if line == "/tools":
            show_tools = not show_tools
            print(f"  (tool echo {'on' if show_tools else 'off'})")
            continue

        t0 = time.perf_counter()
        last_trace = await donna_turn(line, config=config)
        elapsed = time.perf_counter() - t0

        if show_tools:
            _print_tool_trace(last_trace)
        _print_burst(last_trace)
        cost = last_trace.to_dict().get("cost") or 0.0
        turns = last_trace.to_dict().get("num_turns") or 0
        print(f"        · {elapsed:.1f}s · {turns} turns · ${cost:.4f}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--phone", default=None)
    parser.add_argument("--tools", action="store_true", help="echo tool calls per turn")
    args = parser.parse_args()

    user_id = args.user_id or f"repl-{int(time.time())}"
    try:
        asyncio.run(repl(user_id, args.phone, args.tools))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
