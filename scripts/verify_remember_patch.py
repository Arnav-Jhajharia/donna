"""Re-run Turn B against Kai to confirm the relaxed remember(observation)
path actually persists casual observations."""
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

from sqlalchemy import select, text

from db.models import Observation, User
from db.session import async_session
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.context_builder import load_user_model_block, render_turn_context
from donna_runtime.runner import donna_turn
from donna_runtime.session_store import resolve_session_id_db
from donna_runtime.thinking_triage import should_think
from donna_runtime.tracing import TurnTrace

KAI = "11111111-1111-4111-8111-111111111111"

MESSAGE = "had a long talk with my dad on the phone about the company. weird mix of proud and worried."


def _short(name: str) -> str:
    return name.split("__")[-1] if name else "?"


def _summarize(inputs: dict) -> str:
    raw = json.dumps(inputs, default=str)
    return raw if len(raw) <= 240 else raw[:240] + "..."


def _burst(trace: TurnTrace) -> str:
    out: list[str] = []
    for call in trace.to_dict().get("tool_calls", []):
        tool_name = call.get("tool") or call.get("name") or ""
        if not tool_name.endswith("send_burst"):
            continue
        for m in call.get("inputs", {}).get("messages", []):
            if isinstance(m, dict):
                body = m.get("body") or m.get("caption") or ""
                if body:
                    out.append(body)
            elif isinstance(m, str):
                out.append(m)
    return "\n".join(out)


async def main() -> None:
    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.id == KAI))
        ).scalar_one_or_none()
    tz = user.timezone if user and user.timezone else "Asia/Singapore"

    base_config = DonnaAgentConfig(user_id=KAI)
    resume_id = await resolve_session_id_db(
        explicit_session_id=None, user_id=KAI
    )
    state = {
        "user_id": KAI,
        "_user_timezone": tz,
        "_resume_session_id": resume_id,
        "_is_first_message": False,
    }
    turn_context = await render_turn_context(state)
    user_model_block = await load_user_model_block(KAI)
    think, _ = should_think(MESSAGE, state)
    config = replace(
        base_config,
        resume_session_id=resume_id,
        fork_session=False,
        system_context=turn_context,
        user_model_block=user_model_block,
        thinking_enabled=think,
    )

    print("=" * 72)
    print(f"input: {MESSAGE!r}")
    print("=" * 72)
    t0 = time.perf_counter()
    trace = await donna_turn(MESSAGE, config=config)
    elapsed = time.perf_counter() - t0
    print(f"elapsed: {elapsed:.1f}s")
    print()
    print("tool calls:")
    for call in trace.to_dict().get("tool_calls", []):
        short = _short(call.get("tool") or call.get("name") or "?")
        if short == "send_burst":
            continue
        print(f"  · {short}({_summarize(call.get('inputs', {}))})")
        # Tool result
        outs = call.get("outputs") or call.get("output") or call.get("result")
        if outs:
            preview = json.dumps(outs, default=str)
            if len(preview) > 280:
                preview = preview[:280] + "..."
            print(f"    -> {preview}")

    print()
    print("DONNA:")
    for line in (_burst(trace) or "(no terminator)").splitlines():
        print(f"  {line}")

    # Did the observation actually persist?
    print()
    print("=" * 72)
    print("DB CHECK — most recent observations for kai:")
    async with async_session() as s:
        rows = (
            await s.execute(
                select(Observation)
                .where(Observation.user_id == KAI)
                .order_by(Observation.created_at.desc())
                .limit(4)
            )
        ).scalars().all()
        for r in rows:
            fields_str = json.dumps(r.fields)[:140]
            raw_str = (r.raw or "")[:80]
            print(
                f"  {r.created_at.isoformat()[:19]}  type={r.type:18}  "
                f"fields={fields_str}  raw={raw_str!r}"
            )
        # Direct text search for the alcohol/ravi event
        hits = (await s.execute(
            text(
                "SELECT id, type, fields, raw, created_at FROM observations "
                "WHERE user_id = :uid AND (raw ILIKE :p OR fields::text ILIKE :p) "
                "ORDER BY created_at DESC LIMIT 3"
            ),
            {"uid": KAI, "p": "%dad%"},
        )).fetchall()
        print()
        print(f"  'dad' search: {len(hits)} hit(s)")
        for h in hits[:2]:
            print(
                f"    {h.created_at.isoformat()[:19]} type={h.type} "
                f"fields={str(h.fields)[:160]} raw={(h.raw or '')[:120]!r}"
            )


if __name__ == "__main__":
    asyncio.run(main())
