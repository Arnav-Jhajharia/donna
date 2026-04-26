"""Haiku-driven rubric judge for comparing two research answers.

Given a question and two candidate answers (baseline vs pipeline), a Haiku
judge scores each on four axes:

- specificity: concrete detail, not generic.
- citation_quality: sources actually support the claims (best-effort read).
- coverage: addresses the question's scope.
- calibration: flags uncertainty where warranted, avoids overclaiming.

Returns ``RubricResult`` with per-axis scores (0..5) and a one-line verdict.
Never raises. Returns ``None`` when Haiku is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"


class _Scores(BaseModel):
    specificity: int = Field(ge=0, le=5)
    citation_quality: int = Field(ge=0, le=5)
    coverage: int = Field(ge=0, le=5)
    calibration: int = Field(ge=0, le=5)
    verdict: str = Field(description="One-line summary of which answer is stronger and why.")


class _RubricOut(BaseModel):
    baseline: _Scores
    pipeline: _Scores
    winner: str = Field(description="'baseline' | 'pipeline' | 'tie'")


@dataclass(frozen=True)
class AxisScore:
    specificity: int
    citation_quality: int
    coverage: int
    calibration: int
    verdict: str

    @property
    def total(self) -> int:
        return self.specificity + self.citation_quality + self.coverage + self.calibration


@dataclass(frozen=True)
class RubricResult:
    baseline: AxisScore
    pipeline: AxisScore
    winner: str


_SYSTEM = """You are a research-answer judge. Two answers will be given to
the same question. Score each on four 0..5 axes:

- specificity: concrete detail, not generic.
- citation_quality: claims are supported by the sources the answer cites.
- coverage: the answer actually addresses the scope of the question.
- calibration: uncertainty is flagged where warranted; no overclaiming.

Return integer scores 0..5 per axis, a one-line verdict per answer, and a
winner: 'baseline', 'pipeline', or 'tie'.

Be honest. Low scores are fine when warranted."""


async def judge_pair(
    *,
    question: str,
    baseline_answer: str,
    baseline_sources: list[dict[str, str]],
    pipeline_answer: str,
    pipeline_sources: list[dict[str, str]],
) -> RubricResult | None:
    def _format_sources(label: str, sources: list[dict[str, str]]) -> str:
        if not sources:
            return f"{label} sources: (none)"
        lines = [f"{label} sources:"]
        for s in sources[:8]:
            title = (s.get("title") or "").strip()
            url = (s.get("url") or "").strip()
            lines.append(f"- {title} ({url})")
        return "\n".join(lines)

    user = (
        f"Question: {question}\n\n"
        f"Baseline answer:\n{baseline_answer or '(empty)'}\n"
        f"{_format_sources('Baseline', baseline_sources)}\n\n"
        f"Pipeline answer:\n{pipeline_answer or '(empty)'}\n"
        f"{_format_sources('Pipeline', pipeline_sources)}\n\n"
        "Score both now."
    )
    try:
        out = await call_structured(
            model=_MODEL,
            system_prompt=_SYSTEM,
            user_message=user,
            schema=_RubricOut,
            max_tokens=600,
            cache=False,
        )
    except Exception:
        logger.exception("judge_pair: call_structured raised")
        return None
    if out is None:
        return None
    winner = out.winner if out.winner in {"baseline", "pipeline", "tie"} else "tie"
    return RubricResult(
        baseline=AxisScore(
            specificity=out.baseline.specificity,
            citation_quality=out.baseline.citation_quality,
            coverage=out.baseline.coverage,
            calibration=out.baseline.calibration,
            verdict=out.baseline.verdict,
        ),
        pipeline=AxisScore(
            specificity=out.pipeline.specificity,
            citation_quality=out.pipeline.citation_quality,
            coverage=out.pipeline.coverage,
            calibration=out.pipeline.calibration,
            verdict=out.pipeline.verdict,
        ),
        winner=winner,
    )
