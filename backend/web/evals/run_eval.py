"""Run the web research eval: Tavily baseline vs Exa pipeline.

Usage:

    python -m backend.web.evals.run_eval
    python -m backend.web.evals.run_eval --questions q1_compare q3_tradeoffs
    python -m backend.web.evals.run_eval --no-judge   # skip rubric scoring

Skips cleanly when required API keys are missing:
- TAVILY_API_KEY: skip baseline (still runs pipeline)
- EXA_API_KEY:    skip pipeline (still runs baseline)
- ANTHROPIC_API_KEY: skip rubric judge (still runs both answers)

Never posts anywhere. Never modifies state. Prints a table.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

from backend.web.evals.questions import QUESTIONS, EvalQuestion
from backend.web.evals.rubric import RubricResult, judge_pair


# ---------------------------------------------------------------------------
# Baseline: Tavily agentic_search
# ---------------------------------------------------------------------------


async def _run_baseline(question: str) -> dict[str, Any]:
    from backend.web.search import agentic_search

    t0 = time.perf_counter()
    res = await agentic_search(question)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    status = res.get("status")
    if status != "ok":
        return {
            "status": status,
            "answer": "",
            "sources": [],
            "elapsed_ms": elapsed_ms,
            "reason": (res.get("payload") or {}).get("reason", ""),
        }
    payload = res.get("payload") or {}
    return {
        "status": "ok",
        "answer": payload.get("answer", ""),
        "sources": payload.get("sources", []),
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# Pipeline: Exa deep research
# ---------------------------------------------------------------------------


async def _run_pipeline(question: str) -> dict[str, Any]:
    from backend.web.pipeline import run_web_research

    t0 = time.perf_counter()
    answer, trace = await run_web_research(question)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    sources = [
        {"title": s.title, "url": s.url} for s in answer.sources if s.url
    ]
    return {
        "status": "ok" if answer.answer else "empty",
        "answer": answer.answer,
        "confidence": answer.confidence,
        "dissent": answer.dissent,
        "variant": (answer.metadata or {}).get("variant", ""),
        "sources": sources,
        "elapsed_ms": elapsed_ms,
        "trace": {
            "reranker_used": trace.reranker_used,
            "merged_count": trace.merged_count,
            "reranked_count": trace.reranked_count,
            "timings_ms": trace.timings_ms,
        },
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_question_header(q: EvalQuestion) -> None:
    print("")
    print("=" * 88)
    print(f"[{q.id}] {q.question}")
    print(f"    rationale: {q.rationale}")
    print("=" * 88)


def _print_run(label: str, run: dict[str, Any]) -> None:
    print(f"\n--- {label} ---")
    print(f"status: {run.get('status')}  elapsed: {run.get('elapsed_ms')}ms")
    if run.get("reason"):
        print(f"reason: {run['reason']}")
    if "confidence" in run:
        print(f"confidence: {run['confidence']:.2f}  variant: {run.get('variant')}")
    print(f"answer: {_truncate(run.get('answer', ''), 400)}")
    sources = run.get("sources") or []
    if sources:
        print("sources:")
        for s in sources[:5]:
            print(f"  - {_truncate(s.get('title', ''), 60)} ({s.get('url')})")
    if run.get("dissent"):
        print(f"dissent: {_truncate(run['dissent'], 200)}")
    trace = run.get("trace")
    if trace:
        print(
            f"trace: reranker={trace['reranker_used']} "
            f"merged={trace['merged_count']} reranked={trace['reranked_count']} "
            f"timings={trace['timings_ms']}"
        )


def _print_rubric(rubric: RubricResult | None) -> None:
    print("\n--- rubric ---")
    if rubric is None:
        print("rubric: unavailable (ANTHROPIC_API_KEY missing or judge failed)")
        return
    axes = ("specificity", "citation_quality", "coverage", "calibration")
    header = "axis".ljust(18) + "baseline".rjust(10) + "pipeline".rjust(10)
    print(header)
    print("-" * len(header))
    for a in axes:
        b = getattr(rubric.baseline, a)
        p = getattr(rubric.pipeline, a)
        print(a.ljust(18) + str(b).rjust(10) + str(p).rjust(10))
    print("total".ljust(18) + str(rubric.baseline.total).rjust(10) + str(rubric.pipeline.total).rjust(10))
    print(f"\nwinner: {rubric.winner}")
    print(f"baseline verdict: {rubric.baseline.verdict}")
    print(f"pipeline verdict: {rubric.pipeline.verdict}")


def _print_summary(rows: list[tuple[str, RubricResult | None]]) -> None:
    print("")
    print("=" * 88)
    print("SUMMARY")
    print("=" * 88)
    total_baseline = 0
    total_pipeline = 0
    wins = {"baseline": 0, "pipeline": 0, "tie": 0, "skipped": 0}
    for qid, r in rows:
        if r is None:
            wins["skipped"] += 1
            print(f"{qid:18}  (rubric skipped)")
            continue
        total_baseline += r.baseline.total
        total_pipeline += r.pipeline.total
        wins[r.winner] = wins.get(r.winner, 0) + 1
        print(f"{qid:18}  baseline={r.baseline.total:2d}  pipeline={r.pipeline.total:2d}  winner={r.winner}")
    print("-" * 88)
    print(f"TOTAL              baseline={total_baseline:2d}  pipeline={total_pipeline:2d}")
    print(f"wins: {wins}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web pipeline eval")
    parser.add_argument(
        "--questions",
        nargs="*",
        default=None,
        help="Subset of question ids to run (default: all).",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the rubric judge step.",
    )
    return parser.parse_args(argv)


def _select_questions(ids: list[str] | None) -> tuple[EvalQuestion, ...]:
    if not ids:
        return QUESTIONS
    by_id = {q.id: q for q in QUESTIONS}
    missing = [i for i in ids if i not in by_id]
    if missing:
        print(f"warning: unknown question ids: {missing}", file=sys.stderr)
    return tuple(by_id[i] for i in ids if i in by_id)


async def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    questions = _select_questions(args.questions)
    if not questions:
        print("no questions selected.")
        return 1

    have_tavily = bool(os.environ.get("TAVILY_API_KEY", "").strip())
    have_exa = bool(os.environ.get("EXA_API_KEY", "").strip())
    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    print(
        f"keys present: tavily={have_tavily} exa={have_exa} "
        f"anthropic={have_anthropic}"
    )
    if not have_tavily:
        print("  TAVILY_API_KEY missing — baseline will be skipped.")
    if not have_exa:
        print("  EXA_API_KEY missing — pipeline will be skipped.")
    if not have_anthropic:
        print("  ANTHROPIC_API_KEY missing — rubric judge will be skipped.")

    rows: list[tuple[str, RubricResult | None]] = []

    for q in questions:
        _print_question_header(q)

        baseline = await _run_baseline(q.question) if have_tavily else {"status": "skipped", "answer": "", "sources": []}
        pipeline = await _run_pipeline(q.question) if have_exa else {"status": "skipped", "answer": "", "sources": []}

        _print_run("BASELINE (Tavily agentic_search)", baseline)
        _print_run("PIPELINE (Exa deep research)", pipeline)

        rubric: RubricResult | None = None
        if args.no_judge or not have_anthropic:
            rubric = None
        elif baseline.get("answer") or pipeline.get("answer"):
            rubric = await judge_pair(
                question=q.question,
                baseline_answer=baseline.get("answer", ""),
                baseline_sources=baseline.get("sources", []),
                pipeline_answer=pipeline.get("answer", ""),
                pipeline_sources=pipeline.get("sources", []),
            )
        _print_rubric(rubric)
        rows.append((q.id, rubric))

    _print_summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
