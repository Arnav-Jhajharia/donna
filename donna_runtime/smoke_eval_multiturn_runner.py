"""Multi-turn fixture runner.

Drives a MultiTurnFixture end-to-end, feeding each turn's state to the
runner with injected time. Reports per-turn pass/fail + cross-turn
continuity (did later recalls find earlier writes?).

Separated from the single-turn smoke_eval runner because the execution
model is genuinely different: one user session, time moves forward,
state accumulates.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dataclasses import replace as _replace

_RETRY_ON_SILENT_EXIT = os.getenv("DONNA_RETRY_ON_SILENT_EXIT", "1") == "1"
_RETRY_NUDGE = (
    "(system nudge: prior turn ended without send_burst. "
    "call send_burst now with the reply you intended.)"
)

from .config import DonnaAgentConfig
from .context_builder import load_user_model_block, render_turn_context
from .runner import donna_turn
from .session_store import resolve_session_id_db
from .observability import emit_retry_fired
from .smoke_eval import _extract_media_types, _extract_reply_bodies, _terminal_tool, _tool_names
from .smoke_eval_multiturn import MultiTurn, MultiTurnFixture
from .thinking_triage import should_think
from .tracing import TurnTrace

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    turn_id: str
    category: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    terminal_tool: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    tool_call_inputs: list[dict[str, Any]] = field(default_factory=list)
    reply_bodies: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    injected_now: str = ""
    user_message: str = ""
    notes: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0
    # Silent-exit split: did the first pass end with send_burst? If not,
    # did a retry recover? Lets us distinguish "model forgot the terminator
    # but can self-correct" from "model refuses to burst."
    first_try_terminal: str | None = None
    retry_count: int = 0
    recovered_via_retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "category": self.category,
            "passed": self.passed,
            "reasons": self.reasons,
            "terminal_tool": self.terminal_tool,
            "tool_calls": self.tool_calls,
            "tool_call_inputs": self.tool_call_inputs,
            "reply_bodies": self.reply_bodies,
            "media_types": self.media_types,
            "injected_now": self.injected_now,
            "user_message": self.user_message,
            "notes": self.notes,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "first_try_terminal": self.first_try_terminal,
            "retry_count": self.retry_count,
            "recovered_via_retry": self.recovered_via_retry,
        }


@dataclass
class MultiTurnResult:
    fixture_id: str
    user_id: str
    turn_results: list[TurnResult] = field(default_factory=list)
    continuity_checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed_turns(self) -> int:
        return sum(1 for r in self.turn_results if r.passed)

    @property
    def total_turns(self) -> int:
        return len(self.turn_results)

    @property
    def all_turns_passed(self) -> bool:
        return all(r.passed for r in self.turn_results)

    @property
    def continuity_passed(self) -> bool:
        return all(c.get("passed") for c in self.continuity_checks)

    @property
    def silent_exits_first_try(self) -> int:
        return sum(
            1 for r in self.turn_results
            if r.first_try_terminal != "send_burst"
        )

    @property
    def silent_exits_recovered(self) -> int:
        return sum(1 for r in self.turn_results if r.recovered_via_retry)

    @property
    def silent_exits_unrecovered(self) -> int:
        return sum(
            1 for r in self.turn_results
            if r.first_try_terminal != "send_burst"
            and not r.recovered_via_retry
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "user_id": self.user_id,
            "turn_results": [r.to_dict() for r in self.turn_results],
            "continuity_checks": self.continuity_checks,
            "summary": {
                "passed_turns": self.passed_turns,
                "total_turns": self.total_turns,
                "all_turns_passed": self.all_turns_passed,
                "continuity_passed": self.continuity_passed,
                "silent_exits_first_try": self.silent_exits_first_try,
                "silent_exits_recovered": self.silent_exits_recovered,
                "silent_exits_unrecovered": self.silent_exits_unrecovered,
            },
        }


def _evaluate_turn(
    turn: MultiTurn,
    trace: TurnTrace,
    retry_trace: TurnTrace | None = None,
) -> TurnResult:
    result = TurnResult(
        turn_id=turn.turn_id,
        category=turn.category,
        passed=True,
        injected_now=turn.at,
        user_message=turn.message,
        notes=turn.notes,
    )
    first_terminal = _terminal_tool(trace)
    result.first_try_terminal = first_terminal

    # Merge retry into the observed surface. Tool calls and reply bodies from
    # both passes are concatenated; terminal and cost roll up to the final
    # pass. Retry is off the user's back — we're just asking the model to emit
    # the required terminator it forgot.
    if retry_trace is not None:
        result.retry_count = 1
        retry_terminal = _terminal_tool(retry_trace)
        result.terminal_tool = retry_terminal or first_terminal
        result.recovered_via_retry = (
            first_terminal != "send_burst" and retry_terminal == "send_burst"
        )
        result.tool_calls = _tool_names(trace) + _tool_names(retry_trace)
        result.reply_bodies = (
            _extract_reply_bodies(trace) + _extract_reply_bodies(retry_trace)
        )
        result.media_types = (
            _extract_media_types(trace) + _extract_media_types(retry_trace)
        )
    else:
        result.terminal_tool = first_terminal
        result.tool_calls = _tool_names(trace)
        result.reply_bodies = _extract_reply_bodies(trace)
        result.media_types = _extract_media_types(trace)

    for source in (trace, retry_trace):
        if source is None:
            continue
        for call in source.to_dict().get("tool_calls", []):
            name = str(call.get("tool") or call.get("name") or "")
            if name.endswith("send_burst"):
                continue
            result.tool_call_inputs.append({
                "tool": name.split("__")[-1],
                "inputs": call.get("inputs", {}),
            })

    summary = trace.to_dict()
    result.duration_ms = int(summary.get("duration_ms") or 0)
    result.cost_usd = float(summary.get("total_cost_usd") or 0.0)
    if retry_trace is not None:
        retry_summary = retry_trace.to_dict()
        result.duration_ms += int(retry_summary.get("duration_ms") or 0)
        result.cost_usd += float(retry_summary.get("total_cost_usd") or 0.0)

    if result.terminal_tool != "send_burst":
        result.passed = False
        result.reasons.append(
            f"expected terminal send_burst, got {result.terminal_tool}"
        )

    for required in turn.expected_tools:
        if not any(required in name for name in result.tool_calls):
            result.passed = False
            result.reasons.append(f"missing expected tool {required}")

    for banned in turn.banned_tools:
        if any(banned in name for name in result.tool_calls):
            result.passed = False
            result.reasons.append(f"called banned tool {banned}")

    joined = " ".join(result.reply_bodies)
    for phrase in turn.banned_phrases:
        if phrase.lower() in joined.lower():
            result.passed = False
            result.reasons.append(f"banned phrase in reply: {phrase!r}")

    word_count = sum(len(b.split()) for b in result.reply_bodies)
    if word_count > turn.max_reply_words:
        result.passed = False
        result.reasons.append(
            f"reply too long: {word_count} > {turn.max_reply_words}"
        )

    for required_type in turn.expected_media:
        if required_type not in result.media_types:
            result.passed = False
            result.reasons.append(
                f"expected media {required_type!r} not in burst (got {result.media_types})"
            )

    for forbidden_type in turn.forbidden_media:
        if forbidden_type in result.media_types:
            result.passed = False
            result.reasons.append(
                f"forbidden media {forbidden_type!r} appeared in burst"
            )

    return result


async def _ensure_user(user_id: str, timezone: str) -> None:
    """Create a User row if missing so downstream FK constraints are satisfied.

    Idempotent — safe to call on an existing user.
    """
    try:
        from datetime import datetime, timezone as _tz
        from sqlalchemy import select
        from backend.db.models import User
        from backend.db.session import async_session

        async with async_session() as session:
            existing = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                User(
                    id=user_id,
                    phone=f"+multiturn-{user_id}",
                    timezone=timezone,
                    created_at=datetime.now(_tz.utc).replace(tzinfo=None),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("_ensure_user: failed for %s", user_id)


async def run_multiturn_fixture(
    fixture: MultiTurnFixture,
    user_id: str | None = None,
    base_config: DonnaAgentConfig | None = None,
) -> MultiTurnResult:
    user_id = user_id or f"{fixture.user_id_prefix}-{uuid.uuid4().hex[:8]}"
    await _ensure_user(user_id, fixture.timezone)
    base_config = base_config or DonnaAgentConfig(user_id=user_id)

    out = MultiTurnResult(fixture_id=fixture.id, user_id=user_id)

    last_trace: TurnTrace | None = None
    for turn in fixture.turns:
        resume_id = await resolve_session_id_db(
            explicit_session_id=None, user_id=user_id
        )
        state: dict[str, Any] = {
            "user_id": user_id,
            "_user_timezone": fixture.timezone,
            "_resume_session_id": resume_id,
            "_is_first_message": last_trace is None,
            "_injected_now": turn.at,
        }
        turn_context = await render_turn_context(state)
        user_model_block = await load_user_model_block(user_id)
        think, _ = should_think(turn.message, state)

        config = _replace(
            base_config,
            user_id=user_id,
            resume_session_id=resume_id,
            fork_session=False,
            system_context=turn_context,
            user_model_block=user_model_block,
            thinking_enabled=think,
            chat_already_persisted=True,
        )

        logger.info(
            "multiturn[%s] %s @ %s: %s",
            fixture.id, turn.turn_id, turn.at, turn.message[:60],
        )
        try:
            trace = await donna_turn(turn.message, config=config)
        except Exception as exc:
            logger.exception("turn %s crashed", turn.turn_id)
            result = TurnResult(
                turn_id=turn.turn_id,
                category=turn.category,
                passed=False,
                injected_now=turn.at,
            )
            result.reasons.append(f"crash: {exc}")
            out.turn_results.append(result)
            last_trace = None
            continue

        retry_trace: TurnTrace | None = None
        if _RETRY_ON_SILENT_EXIT and _terminal_tool(trace) != "send_burst":
            emit_retry_fired(
                kind="silent_exit",
                reason=f"first-try terminal={_terminal_tool(trace)!r}",
                source="multiturn_runner",
            )
            retry_trace = await _fire_silent_exit_retry(
                user_id=user_id,
                fixture_timezone=fixture.timezone,
                injected_now=turn.at,
                base_config=base_config,
            )

        result = _evaluate_turn(turn, trace, retry_trace=retry_trace)
        out.turn_results.append(result)
        last_trace = retry_trace or trace

    out.continuity_checks = _continuity_checks(fixture, out.turn_results)
    return out


async def _fire_silent_exit_retry(
    *,
    user_id: str,
    fixture_timezone: str,
    injected_now: str,
    base_config: DonnaAgentConfig,
) -> TurnTrace | None:
    """Second pass on the same session after a silent exit.

    Resolves a fresh session id so the SDK resumes the conversation that just
    happened, injects a terse system nudge as a user turn, and lets the model
    emit the send_burst it forgot. Best-effort — any failure returns None.
    """
    try:
        resume_id = await resolve_session_id_db(
            explicit_session_id=None, user_id=user_id
        )
        state: dict[str, Any] = {
            "user_id": user_id,
            "_user_timezone": fixture_timezone,
            "_resume_session_id": resume_id,
            "_is_first_message": False,
            "_injected_now": injected_now,
        }
        turn_context = await render_turn_context(state)
        user_model_block = await load_user_model_block(user_id)
        config = _replace(
            base_config,
            user_id=user_id,
            resume_session_id=resume_id,
            fork_session=False,
            system_context=turn_context,
            user_model_block=user_model_block,
            thinking_enabled=False,
            chat_already_persisted=True,
        )
        logger.info("multiturn retry: silent exit, firing nudge")
        return await donna_turn(_RETRY_NUDGE, config=config)
    except Exception:
        logger.exception("silent-exit retry failed")
        return None


def _continuity_checks(
    fixture: MultiTurnFixture, turn_results: list[TurnResult]
) -> list[dict[str, Any]]:
    """Cross-turn assertions. Each check is a dict with keys:
       name, passed, reason, evidence.
    """
    by_id = {r.turn_id: r for r in turn_results}
    checks: list[dict[str, Any]] = []

    # Continuity-1: day-2 spend recall should reference 6 (the day-1 coffee) in reply.
    spend = by_id.get("d2_spend_recall")
    if spend:
        reply = " ".join(spend.reply_bodies).lower()
        has_six = "6" in reply or "six" in reply
        checks.append({
            "name": "d2_spend_recall mentions day-1 expense ($6)",
            "passed": bool(spend.passed and has_six),
            "reason": None if has_six else "reply did not mention 6 from day 1 coffee log",
            "evidence": " | ".join(spend.reply_bodies)[:200],
        })

    # Continuity-2: day-3 multi-night sleep recall should reference 4 and 5.
    sleep_week = by_id.get("d3_sleep_week")
    if sleep_week:
        reply = " ".join(sleep_week.reply_bodies).lower()
        has_both = "4" in reply and "5" in reply
        checks.append({
            "name": "d3_sleep_week mentions both prior nights (4h, 5h)",
            "passed": bool(sleep_week.passed and has_both),
            "reason": None if has_both else "reply missing one or both of 4/5 hours",
            "evidence": " | ".join(sleep_week.reply_bodies)[:200],
        })

    # Continuity-3: day-3 forgetting check should mention sarah (tracked day 1).
    forgetting = by_id.get("d3_forgetting_check")
    if forgetting:
        reply = " ".join(forgetting.reply_bodies).lower()
        has_sarah = "sarah" in reply
        checks.append({
            "name": "d3_forgetting_check surfaces sarah open loop",
            "passed": bool(forgetting.passed and has_sarah),
            "reason": None if has_sarah else "reply did not surface sarah from day-1 open loop",
            "evidence": " | ".join(forgetting.reply_bodies)[:200],
        })

    # Continuity-4: day-3 mood recall should reference 3 (the day-1 mood log).
    mood_recall = by_id.get("d3_mood_recall")
    if mood_recall:
        reply = " ".join(mood_recall.reply_bodies).lower()
        has_three = "3" in reply
        checks.append({
            "name": "d3_mood_recall mentions monday mood (3)",
            "passed": bool(mood_recall.passed and has_three),
            "reason": None if has_three else "reply did not surface monday mood of 3",
            "evidence": " | ".join(mood_recall.reply_bodies)[:200],
        })

    # Continuity-5: day-3 close_loop should reference sarah.
    close = by_id.get("d3_close_loop")
    if close:
        reply = " ".join(close.reply_bodies).lower()
        has_sarah = "sarah" in reply
        checks.append({
            "name": "d3_close_loop references sarah loop",
            "passed": bool(close.passed and has_sarah),
            "reason": None if has_sarah else "close_open_loop reply did not reference sarah",
            "evidence": " | ".join(close.reply_bodies)[:200],
        })

    return checks


async def dump_user_state(user_id: str) -> dict[str, Any]:
    """Post-arc snapshot of what the backends accumulated for this user.

    Best-effort — any backend that isn't reachable comes back as {}.
    Use after a fixture to see whether the writes landed and what the
    Living Profile / graph / open loops / observations look like.
    """
    snapshot: dict[str, Any] = {"user_id": user_id}

    try:
        from sqlalchemy import select
        from backend.db.models import Observation, OpenLoop, ChatMessage, User
        from backend.db.session import async_session

        async with async_session() as session:
            obs_rows = (
                await session.execute(
                    select(Observation).where(Observation.user_id == user_id)
                )
            ).scalars().all()
            loop_rows = (
                await session.execute(
                    select(OpenLoop).where(OpenLoop.user_id == user_id)
                )
            ).scalars().all()
            chat_rows = (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.user_id == user_id)
                )
            ).scalars().all()
            user_row = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()

        snapshot["observations"] = [
            {
                "type": o.type,
                "fields": o.fields,
                "event_time": str(o.event_time),
                "raw": (o.raw or "")[:80],
            }
            for o in obs_rows
        ]
        snapshot["open_loops"] = [
            {"id": str(l.id), "content": (l.content or "")[:120], "status": l.status}
            for l in loop_rows
        ]
        snapshot["chat_messages_count"] = len(chat_rows)
        snapshot["user"] = {
            "timezone": getattr(user_row, "timezone", None),
            "exists": user_row is not None,
        }
    except Exception as exc:
        snapshot["db_error"] = str(exc)

    try:
        from backend.memory.user_facts.rendering import load_and_render
        snapshot["living_profile"] = (await load_and_render(user_id))[:2000]
    except Exception as exc:
        snapshot["living_profile_error"] = str(exc)

    return snapshot


def write_multiturn_jsonl(result: MultiTurnResult, path: str | Path) -> Path:
    """Emit one line per turn to JSONL for post-hoc analysis.

    Schema per line: TurnResult.to_dict() + {"fixture_id", "user_id"}.
    Final line is the continuity_checks summary.

    Intended use:
      jq '. | select(.passed == false)' traces.jsonl
      jq '.tool_calls' traces.jsonl
      jq 'select(.category == "memory_recall") | {turn_id, tool_calls, reply_bodies}' traces.jsonl
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for r in result.turn_results:
            row = r.to_dict()
            row["fixture_id"] = result.fixture_id
            row["user_id"] = result.user_id
            fh.write(json.dumps(row, default=str) + "\n")
        fh.write(json.dumps({
            "fixture_id": result.fixture_id,
            "user_id": result.user_id,
            "_kind": "continuity_summary",
            "continuity_checks": result.continuity_checks,
            "summary": {
                "passed_turns": result.passed_turns,
                "total_turns": result.total_turns,
                "all_turns_passed": result.all_turns_passed,
                "continuity_passed": result.continuity_passed,
                "silent_exits_first_try": result.silent_exits_first_try,
                "silent_exits_recovered": result.silent_exits_recovered,
                "silent_exits_unrecovered": result.silent_exits_unrecovered,
            },
        }, default=str) + "\n")
    return out_path


def print_multiturn_report(result: MultiTurnResult) -> int:
    print(f"\n=== multi-turn: {result.fixture_id} "
          f"(user_id={result.user_id}) ===")
    print(f"\nturns: {result.passed_turns}/{result.total_turns} passed")
    by_cat: dict[str, list[TurnResult]] = {}
    for r in result.turn_results:
        by_cat.setdefault(r.category, []).append(r)
    for cat, items in sorted(by_cat.items()):
        cat_pass = sum(1 for r in items if r.passed)
        print(f"  {cat:<16} {cat_pass}/{len(items)}")

    silent_first = [
        r for r in result.turn_results
        if r.first_try_terminal != "send_burst"
    ]
    recovered = [r for r in silent_first if r.recovered_via_retry]
    unrecovered = [
        r for r in silent_first
        if not r.recovered_via_retry
    ]
    if silent_first:
        print(
            f"\nsilent exits: {len(silent_first)} first-try, "
            f"{len(recovered)} recovered via retry, "
            f"{len(unrecovered)} unrecovered"
        )

    print("\nper-turn detail:")
    for r in result.turn_results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.turn_id} @ {r.injected_now}")
        if not r.passed:
            for reason in r.reasons:
                print(f"     - {reason}")
            if r.tool_calls:
                print(f"     tools: {r.tool_calls}")

    print("\ncontinuity:")
    for c in result.continuity_checks:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['name']}")
        if not c["passed"] and c.get("reason"):
            print(f"     - {c['reason']}")
            if c.get("evidence"):
                print(f"     evidence: {c['evidence']}")

    overall_ok = result.all_turns_passed and result.continuity_passed
    print(f"\nresult: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


def main() -> int:
    import argparse
    import asyncio

    from .smoke_eval_multiturn import ALL_MULTITURN_FIXTURES

    parser = argparse.ArgumentParser(description="Donna multi-turn eval runner")
    parser.add_argument(
        "--fixture",
        default="three_day_arc",
        help="Fixture id to run (see ALL_MULTITURN_FIXTURES)",
    )
    parser.add_argument("--user-id", default=None)
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write JSONL trace for post-hoc analysis.",
    )
    parser.add_argument(
        "--dump-state",
        action="store_true",
        help="After the arc, snapshot the user's DB state (observations, loops, Living Profile).",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run LLM-as-judge over each turn (scores awareness/discipline/voice).",
    )
    args = parser.parse_args()

    by_id = {fx.id: fx for fx in ALL_MULTITURN_FIXTURES}
    if args.fixture not in by_id:
        print(f"unknown fixture {args.fixture!r}. available: {sorted(by_id)}")
        return 2
    fixture = by_id[args.fixture]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    async def _amain() -> int:
        """All three phases (run + dump + judge) share one event loop so the
        SQLAlchemy async engine stays on its original loop. Running them in
        separate asyncio.run() calls triggers 'attached to a different loop'
        errors on the post-run queries.
        """
        result = await run_multiturn_fixture(fixture, user_id=args.user_id)
        local_rc = print_multiturn_report(result)

        if args.output:
            path = write_multiturn_jsonl(result, args.output)
            print(f"\ntrace written to {path}")

        if args.dump_state:
            state = await dump_user_state(result.user_id)
            print("\n=== post-arc state dump ===")
            print(json.dumps(state, indent=2, default=str))
            if args.output:
                state_path = Path(args.output).with_suffix(".state.json")
                state_path.write_text(json.dumps(state, indent=2, default=str))
                print(f"\nstate dump written to {state_path}")

        if args.judge:
            from .awareness_judge import (
                judge_multiturn_result,
                print_judge_report,
                summarize_verdicts,
            )
            verdicts = await judge_multiturn_result(result, fixture)
            print_judge_report(verdicts)
            if args.output:
                judge_path = Path(args.output).with_suffix(".judge.json")
                judge_path.write_text(
                    json.dumps(
                        {
                            "summary": summarize_verdicts(verdicts),
                            "verdicts": [v.to_dict() for v in verdicts],
                        },
                        indent=2,
                        default=str,
                    )
                )
                print(f"\njudge report written to {judge_path}")

        return local_rc

    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
