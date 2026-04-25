"""Smoke eval scaffold tests — structural + evaluator logic, no live LLM."""
from __future__ import annotations

import unittest

from donna_runtime.smoke_eval import _evaluate
from donna_runtime.smoke_eval_fixtures import SMOKE_FIXTURES, SmokeFixture
from donna_runtime.tracing import TurnTrace


def _trace_with_burst(message: str, tool_calls: list[tuple[str, dict]]) -> TurnTrace:
    trace = TurnTrace(message)
    for i, (name, inputs) in enumerate(tool_calls):
        trace.record_tool_call(name, inputs, f"call_{i}")
    return trace


class SmokeFixtureShapeTests(unittest.TestCase):
    def test_has_enough_fixtures_per_category(self) -> None:
        by_cat: dict[str, int] = {}
        for f in SMOKE_FIXTURES:
            by_cat[f.category] = by_cat.get(f.category, 0) + 1
        for required in ("voice", "tool_choice", "memory_write", "memory_recall", "widget"):
            self.assertGreaterEqual(
                by_cat.get(required, 0),
                3,
                f"category {required} needs at least 3 fixtures (has {by_cat.get(required, 0)})",
            )

    def test_unique_ids(self) -> None:
        ids = [f.id for f in SMOKE_FIXTURES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_fixture_has_terminal(self) -> None:
        for f in SMOKE_FIXTURES:
            self.assertEqual(f.expected_terminal, "send_burst")

    def test_every_fixture_has_category(self) -> None:
        valid = {"voice", "tool_choice", "memory_write", "memory_recall", "widget", "mixed"}
        for f in SMOKE_FIXTURES:
            self.assertIn(f.category, valid)


class EvaluatorTests(unittest.TestCase):
    def test_pass_on_correct_terminal_and_clean_reply(self) -> None:
        f = SmokeFixture(id="x", message="hi", expected_terminal="send_burst")
        trace = _trace_with_burst(
            "hi", [("mcp__donna__send_burst", {"messages": [{"type": "text", "body": "ok"}]})]
        )
        r = _evaluate(f, trace)
        self.assertTrue(r.passed, r.reasons)

    def test_fail_on_missing_terminal(self) -> None:
        f = SmokeFixture(id="x", message="hi", expected_terminal="send_burst")
        trace = _trace_with_burst(
            "hi", [("mcp__donna__recall_graph", {"query": "x"})]
        )
        r = _evaluate(f, trace)
        self.assertFalse(r.passed)

    def test_fail_on_banned_phrase(self) -> None:
        f = SmokeFixture(id="x", message="hi", expected_terminal="send_burst")
        trace = _trace_with_burst(
            "hi",
            [(
                "mcp__donna__send_burst",
                {"messages": [{"type": "text", "body": "I understand you want help"}]},
            )],
        )
        r = _evaluate(f, trace)
        self.assertFalse(r.passed)
        self.assertTrue(any("banned phrase" in reason for reason in r.reasons))

    def test_fail_on_missing_expected_tool(self) -> None:
        f = SmokeFixture(
            id="x",
            message="hi",
            expected_terminal="send_burst",
            expected_tools=("mcp__donna__read_tracker",),
        )
        trace = _trace_with_burst(
            "hi", [("mcp__donna__send_burst", {"messages": [{"type": "text", "body": "ok"}]})]
        )
        r = _evaluate(f, trace)
        self.assertFalse(r.passed)

    def test_fail_on_reply_too_long(self) -> None:
        f = SmokeFixture(
            id="x", message="hi", expected_terminal="send_burst", max_reply_words=5
        )
        trace = _trace_with_burst(
            "hi",
            [(
                "mcp__donna__send_burst",
                {"messages": [{"type": "text", "body": "one two three four five six seven eight"}]},
            )],
        )
        r = _evaluate(f, trace)
        self.assertFalse(r.passed)
        self.assertTrue(any("too long" in reason for reason in r.reasons))


if __name__ == "__main__":
    unittest.main()
