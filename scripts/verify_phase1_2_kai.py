"""Run two real brain turns against Kai to verify the new
SITUATIONAL AWARENESS nudges actually fire the expected tools.

Turn A — topic mention. The user asks about a past doc/topic Kai
cares about. We expect Donna to call ``recall`` (or
``recall_document_chunks``) before answering, because the prompt
now tells her to.

Turn B — loggable event. The user states "had too many beers last
night." We expect Donna to call ``log_observation`` while she
responds.

Prints each turn's tool calls and final response. Hits real
Anthropic + Supermemory + Postgres.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv()

from sqlalchemy import select

from db.models import User
from db.session import async_session
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.context_builder import load_user_model_block, render_turn_context
from donna_runtime.runner import donna_turn
from donna_runtime.session_store import resolve_session_id_db
from donna_runtime.thinking_triage import should_think
from donna_runtime.tracing import TurnTrace

KAI = "11111111-1111-4111-8111-111111111111"

TURNS = [
    (
        "topic mention (expect recall)",
        "what was in that term sheet from saurabh? need to refresh on the vesting terms",
    ),
    (
        "loggable event (expect log_observation)",
        "had like 5 beers last night with ravi, feel rough this morning",
    ),
]


async def _user_tz(user_id: str) -> str:
    async with async_session() as session:
        row = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    return (row.timezone if row and row.timezone else "Asia/Singapore")


def _short(name: str) -> str:
    return name.split("__")[-1] if name else "?"


def _summarize_inputs(inputs: dict) -> str:
    raw = json.dumps(inputs, default=str)
    if len(raw) > 200:
        raw = raw[:200] + "..."
    return raw


def _summarize_burst(trace: TurnTrace) -> str:
    out: list[str] = []
    for call in trace.to_dict().get("tool_calls", []):
        tool = call.get("tool") or call.get("name") or ""
        if tool.endswith("send_burst"):
            for m in call.get("inputs", {}).get("messages", []):
                if isinstance(m, dict):
                    body = m.get("body") or m.get("caption") or ""
                    if body:
                        out.append(body)
                elif isinstance(m, str):
                    out.append(m)
    return "\n".join(out)


def _tool_calls(trace: TurnTrace) -> list[dict]:
    return trace.to_dict().get("tool_calls", []) or []


async def run_turn(user_id: str, message: str, *, base_config: DonnaAgentConfig, is_first: bool, tz: str) -> TurnTrace:
    resume_id = await resolve_session_id_db(
        explicit_session_id=None, user_id=user_id
    )
    state = {
        "user_id": user_id,
        "_user_timezone": tz,
        "_resume_session_id": resume_id,
        "_is_first_message": is_first,
    }
    turn_context = await render_turn_context(state)
    user_model_block = await load_user_model_block(user_id)
    think, _ = should_think(message, state)
    config = replace(
        base_config,
        resume_session_id=resume_id,
        fork_session=False,
        system_context=turn_context,
        user_model_block=user_model_block,
        thinking_enabled=think,
    )
    return await donna_turn(message, config=config)


async def main() -> None:
    tz = await _user_tz(KAI)
    base_config = DonnaAgentConfig(user_id=KAI)
    first = True
    for label, message in TURNS:
        print()
        print("=" * 72)
        print(f"TURN: {label}")
        print(f"input: {message!r}")
        print("=" * 72)
        t0 = time.perf_counter()
        try:
            trace = await run_turn(
                KAI,
                message,
                base_config=base_config,
                is_first=first,
                tz=tz,
            )
        except Exception as exc:
            print(f"  TURN RAISED: {type(exc).__name__}: {exc}")
            first = False
            continue
        elapsed = time.perf_counter() - t0

        calls = _tool_calls(trace)
        names = [(_short(c.get("tool") or c.get("name") or "?")) for c in calls]
        print(f"\nelapsed: {elapsed:.1f}s")
        print(f"tool calls in order: {names}")
        for c in calls:
            short = _short(c.get("tool") or c.get("name") or "?")
            if short == "send_burst":
                continue
            print(f"  · {short}({_summarize_inputs(c.get('inputs', {}))})")

        burst = _summarize_burst(trace)
        print()
        print("DONNA:")
        for line in (burst or "(no terminator)").splitlines():
            print(f"  {line}")

        first = False


if __name__ == "__main__":
    asyncio.run(main())
