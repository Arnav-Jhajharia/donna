"""Turn-level idempotency guard on write tools.

The PreToolUse hook denies a second call to any of the guarded write tools
when the (tool_name, args_hash) pair has already fired in this turn.
Reads are intentionally not guarded — repeating a read is wasteful but safe.
"""
from __future__ import annotations

import asyncio

import pytest

from donna_runtime.hooks import (
    _IDEMPOTENCY_GUARDED_TOOLS,
    pre_tool_hook,
    trace_hook_context,
)
from donna_runtime.tracing import TurnTrace


def _pre(name: str, args: dict) -> dict:
    return {"tool_name": f"mcp__donna__{name}", "tool_input": args}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class TestIdempotencyGuard:
    def test_guarded_tool_list_matches_contract(self) -> None:
        assert set(_IDEMPOTENCY_GUARDED_TOOLS) == {
            "log_observation",
            "track_open_loop",
            "schedule_reminder",
        }

    def test_first_call_to_guarded_tool_allowed(self) -> None:
        async def scenario() -> dict:
            trace = TurnTrace("log a 6 dollar coffee")
            with trace_hook_context(trace, user_id="u1"):
                return await pre_tool_hook(
                    _pre("log_observation", {"type": "expense", "fields": {"amount_usd": 6}}),
                    "call_1",
                    None,
                )

        out = _run(scenario())
        assert out == {}

    def test_duplicate_guarded_call_in_same_turn_denied(self) -> None:
        async def scenario() -> dict:
            trace = TurnTrace("log a 6 dollar coffee")
            args = {"type": "expense", "fields": {"amount_usd": 6}}
            with trace_hook_context(trace, user_id="u1"):
                first = await pre_tool_hook(_pre("log_observation", args), "call_1", None)
                second = await pre_tool_hook(_pre("log_observation", args), "call_2", None)
            return {"first": first, "second": second}

        out = _run(scenario())
        assert out["first"] == {}
        decision = out["second"].get("hookSpecificOutput", {})
        assert decision.get("permissionDecision") == "deny"
        assert "identical args this turn" in decision.get("permissionDecisionReason", "")

    def test_different_args_are_not_duplicates(self) -> None:
        async def scenario() -> tuple[dict, dict]:
            trace = TurnTrace("log two coffees")
            with trace_hook_context(trace, user_id="u1"):
                first = await pre_tool_hook(
                    _pre("log_observation", {"type": "expense", "fields": {"amount_usd": 6}}),
                    "call_1",
                    None,
                )
                second = await pre_tool_hook(
                    _pre("log_observation", {"type": "expense", "fields": {"amount_usd": 7}}),
                    "call_2",
                    None,
                )
            return first, second

        first, second = _run(scenario())
        assert first == {}
        assert second == {}

    def test_reads_are_not_guarded(self) -> None:
        async def scenario() -> tuple[dict, dict]:
            trace = TurnTrace("how much did i spend")
            args = {"name": "expenses_week"}
            with trace_hook_context(trace, user_id="u1"):
                first = await pre_tool_hook(_pre("read_tracker", args), "call_1", None)
                second = await pre_tool_hook(_pre("read_tracker", args), "call_2", None)
            return first, second

        first, second = _run(scenario())
        assert first == {}
        assert second == {}

    def test_signatures_reset_between_turns(self) -> None:
        """A duplicate-args call in a *new* turn must not be blocked by a prior turn."""
        async def turn(tag: str) -> dict:
            trace = TurnTrace(f"turn {tag}")
            args = {"type": "expense", "fields": {"amount_usd": 6}}
            with trace_hook_context(trace, user_id="u1"):
                return await pre_tool_hook(_pre("log_observation", args), f"call_{tag}", None)

        async def scenario() -> tuple[dict, dict]:
            first_turn = await turn("a")
            second_turn = await turn("b")
            return first_turn, second_turn

        first, second = _run(scenario())
        assert first == {}
        assert second == {}

    def test_track_open_loop_and_schedule_reminder_also_guarded(self) -> None:
        async def check(tool_name: str) -> dict:
            trace = TurnTrace("test")
            args = {"content": "follow up with sarah"} if tool_name == "track_open_loop" else {
                "text": "take meds",
                "in_minutes": 30,
            }
            with trace_hook_context(trace, user_id="u1"):
                await pre_tool_hook(_pre(tool_name, args), "call_1", None)
                return await pre_tool_hook(_pre(tool_name, args), "call_2", None)

        for name in ("track_open_loop", "schedule_reminder"):
            result = _run(check(name))
            decision = result.get("hookSpecificOutput", {})
            assert decision.get("permissionDecision") == "deny", f"{name} should be guarded"
