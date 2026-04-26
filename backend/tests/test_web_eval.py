"""Smoke tests for the eval harness — no live HTTP / LLM calls."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.web.evals import rubric as rubric_mod
from backend.web.evals import run_eval
from backend.web.evals.questions import QUESTIONS


def test_questions_has_five_research_grade_items():
    assert len(QUESTIONS) == 5
    ids = {q.id for q in QUESTIONS}
    assert len(ids) == 5  # all unique


@pytest.mark.asyncio
async def test_rubric_degrades_when_call_structured_returns_none(monkeypatch):
    async def fake(**kwargs):
        return None

    monkeypatch.setattr(rubric_mod, "call_structured", fake)
    out = await rubric_mod.judge_pair(
        question="q",
        baseline_answer="a",
        baseline_sources=[{"title": "t", "url": "https://a.test"}],
        pipeline_answer="b",
        pipeline_sources=[{"title": "t2", "url": "https://b.test"}],
    )
    assert out is None


@pytest.mark.asyncio
async def test_rubric_returns_scores_when_judge_succeeds(monkeypatch):
    class _Sub:
        specificity = 3
        citation_quality = 4
        coverage = 3
        calibration = 3
        verdict = "ok answer"

    class _Sub2(_Sub):
        specificity = 4
        coverage = 4

    class _Out:
        baseline = _Sub()
        pipeline = _Sub2()
        winner = "pipeline"

    async def fake(**kwargs):
        return _Out()

    monkeypatch.setattr(rubric_mod, "call_structured", fake)
    out = await rubric_mod.judge_pair(
        question="q",
        baseline_answer="a",
        baseline_sources=[],
        pipeline_answer="b",
        pipeline_sources=[],
    )
    assert out is not None
    assert out.winner == "pipeline"
    assert out.baseline.total == 3 + 4 + 3 + 3
    assert out.pipeline.total == 4 + 4 + 4 + 3


@pytest.mark.asyncio
async def test_run_eval_skips_cleanly_without_keys(monkeypatch, capsys):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    code = await run_eval.main(["--questions", "q1_compare", "--no-judge"])
    assert code == 0

    out = capsys.readouterr().out
    assert "tavily=False" in out
    assert "exa=False" in out
    assert "SUMMARY" in out


@pytest.mark.asyncio
async def test_run_eval_unknown_question_is_skipped(monkeypatch, capsys):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    code = await run_eval.main(["--questions", "nope_not_real", "--no-judge"])
    assert code == 1
    captured = capsys.readouterr()
    assert "unknown question ids" in captured.err
