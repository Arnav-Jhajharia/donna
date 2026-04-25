"""Tests for the memory stress-test harness (Phase 3).

Exercises matrix shape, judge parsing, runner orchestration with a fake
turn runner + fake judge. No DB, no LLM.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts._stress_matrix.cases import StressCase, all_cases
from scripts._stress_matrix.judge import (
    JudgeContext,
    grade,
    parse_verdict,
    render_prompt,
)
from scripts._stress_matrix.runner import TurnResult, run_matrix
from scripts._stress_matrix.trace import (
    JudgeVerdict,
    StressTrace,
    summarize,
    write_jsonl,
)


class TestCatalogue:
    def test_matrix_sections_all_present(self) -> None:
        cases = all_cases()
        sections = {c.section for c in cases}
        assert sections == {
            "single_hop",
            "multi_hop",
            "temporal",
            "derivation",
            "correction",
            "failure_injection",
            "voice_coherence",
        }

    def test_case_ids_are_unique(self) -> None:
        cases = all_cases()
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids)), "case ids must be unique"

    def test_counts_per_section_match_plan(self) -> None:
        counts: dict[str, int] = {}
        for c in all_cases():
            counts[c.section] = counts.get(c.section, 0) + 1
        assert counts["single_hop"] == 7
        assert counts["multi_hop"] == 6
        assert counts["temporal"] == 6
        assert counts["derivation"] == 5
        assert counts["correction"] == 5
        assert counts["failure_injection"] == 5
        assert counts["voice_coherence"] == 4

    def test_every_case_has_rubric(self) -> None:
        for case in all_cases():
            assert case.pass_criteria, f"case {case.id} has no pass_criteria"


class TestJudge:
    def _case(self) -> StressCase:
        return StressCase(
            id="t",
            section="single_hop",
            query="how much did i spend",
            expected_backends=("observations",),
            pass_criteria="reply cites a numeric total",
        )

    def test_render_prompt_includes_query_and_rubric(self) -> None:
        ctx = JudgeContext(case=self._case(), reply_body="you spent 42 SGD", backends_hit=("observations",))
        prompt = render_prompt(ctx)
        assert "how much did i spend" in prompt
        assert "reply cites a numeric total" in prompt
        assert "you spent 42 SGD" in prompt
        assert "observations" in prompt

    def test_parse_verdict_pure_json(self) -> None:
        v = parse_verdict('{"passed": true, "reason": "cites 42 SGD"}', case=self._case())
        assert v.passed is True
        assert v.reason == "cites 42 SGD"

    def test_parse_verdict_with_surrounding_text(self) -> None:
        v = parse_verdict(
            'Here is my verdict: {"passed": false, "reason": "no number"} thanks',
            case=self._case(),
        )
        assert v.passed is False
        assert v.reason == "no number"

    def test_parse_verdict_non_json_is_failure(self) -> None:
        v = parse_verdict("I think this passes", case=self._case())
        assert v.passed is False
        assert "non-JSON" in v.reason

    @pytest.mark.asyncio
    async def test_grade_round_trip(self) -> None:
        class FakeClient:
            async def grade(self, prompt: str) -> str:
                del prompt
                return '{"passed": true, "reason": "ok"}'

        ctx = JudgeContext(case=self._case(), reply_body="42 SGD", backends_hit=("observations",))
        verdict = await grade(FakeClient(), ctx)
        assert verdict.passed is True
        assert verdict.reason == "ok"


class TestRunner:
    @pytest.mark.asyncio
    async def test_run_matrix_with_fake_runner(self) -> None:
        cases = all_cases()[:3]

        class FakeRunner:
            async def run(self, case: StressCase, *, user_id: str) -> TurnResult:
                del user_id
                return TurnResult(
                    reply_body=f"reply for {case.id}",
                    tools_called=("recall",),
                    backends_hit=("observations",),
                    latency_ms={"total_turn": 123},
                    tokens={"input": 10, "output": 5},
                )

        class FakeJudge:
            async def grade(self, prompt: str) -> str:
                del prompt
                return '{"passed": true, "reason": "good"}'

        rows = await run_matrix(
            cases,
            user_id="u",
            turn_runner=FakeRunner(),
            judge_client=FakeJudge(),
        )
        assert len(rows) == 3
        assert all(r.judge.passed for r in rows)
        assert rows[0].backends_hit == ("observations",)

    @pytest.mark.asyncio
    async def test_runner_handles_turn_exception(self) -> None:
        class BrokenRunner:
            async def run(self, case: StressCase, *, user_id: str) -> TurnResult:
                del case, user_id
                raise RuntimeError("db down")

        rows = await run_matrix(
            [all_cases()[0]],
            user_id="u",
            turn_runner=BrokenRunner(),
            judge_client=None,
        )
        assert rows[0].error is not None
        assert rows[0].judge.passed is False

    @pytest.mark.asyncio
    async def test_missing_judge_marks_skipped(self) -> None:
        class FakeRunner:
            async def run(self, case: StressCase, *, user_id: str) -> TurnResult:
                del case, user_id
                return TurnResult(
                    reply_body="r",
                    tools_called=(),
                    backends_hit=(),
                    latency_ms={"total_turn": 1},
                    tokens={},
                )

        rows = await run_matrix(
            [all_cases()[0]],
            user_id="u",
            turn_runner=FakeRunner(),
            judge_client=None,
        )
        assert rows[0].judge.passed is False
        assert "judge skipped" in rows[0].judge.reason


class TestTraceIO:
    def test_write_jsonl_round_trip(self, tmp_path: Path) -> None:
        row = StressTrace(
            query_id="a",
            section="single_hop",
            query="q",
            reply_body="r",
            tools_called=("recall",),
            backends_hit=("observations",),
            expected_backends=("observations",),
            latency_ms={"total_turn": 12},
            tokens={"input": 1, "output": 2},
            judge=JudgeVerdict(passed=True, reason="ok", rubric="cites total"),
        )
        out = tmp_path / "stress.jsonl"
        write_jsonl(out, [row, row])
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        payload = json.loads(lines[0])
        assert payload["query_id"] == "a"
        assert payload["judge"]["passed"] is True
        assert payload["tools_called"] == ["recall"]

    def test_summarize_buckets_by_section(self) -> None:
        def _row(section: str, passed: bool, error: str | None = None) -> StressTrace:
            return StressTrace(
                query_id=f"{section}-{passed}-{error}",
                section=section,
                query="q",
                reply_body="r",
                tools_called=(),
                backends_hit=(),
                expected_backends=(),
                latency_ms={},
                tokens={},
                judge=JudgeVerdict(passed=passed, reason=""),
                error=error,
            )

        summary = summarize(
            [
                _row("single_hop", True),
                _row("single_hop", False),
                _row("multi_hop", True),
                _row("multi_hop", False, error="boom"),
            ]
        )
        assert summary["total"] == 4
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["error"] == 1
        assert summary["by_section"]["single_hop"] == {"passed": 1, "failed": 1, "error": 0}
        assert summary["by_section"]["multi_hop"] == {"passed": 1, "failed": 0, "error": 1}
