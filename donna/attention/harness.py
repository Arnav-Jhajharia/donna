"""End-to-end Attention pipeline orchestrator.

Stages: normalize → retrieve → author → dry_run. Each stage is timed;
the final result bundles everything for CLI display or test assertions.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from donna.attention.author import AuthorResult, _looks_like_bare_reminder, author_spec
from donna.attention.dry_run import DryRunResult, dry_run
from donna.attention.normalize import (
    NormalizedIntent,
    NormalizedSignals,
    UserContext,
    _heuristic_normalize,
    normalize_intent,
)
from donna.attention.retrieve import Retrieved, retrieve_top_k

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageTiming:
    stage: str
    ms: float


@dataclass(frozen=True)
class PipelineResult:
    raw_intent: str
    normalized: NormalizedIntent
    retrieved: tuple[Retrieved, ...]
    authored: AuthorResult
    preview: DryRunResult
    timings: tuple[StageTiming, ...] = field(default_factory=tuple)

    @property
    def total_ms(self) -> float:
        return sum(t.ms for t in self.timings)


async def run_attention_pipeline(
    raw_intent: str,
    user_context: UserContext,
    *,
    k: int = 3,
) -> PipelineResult:
    timings: list[StageTiming] = []

    # E1: bare-reminder fast-path — skip retrieve AND normalize entirely.
    if _looks_like_bare_reminder(raw_intent):
        t0 = time.perf_counter()
        normalized = NormalizedIntent(
            raw_text=raw_intent,
            normalized_text=raw_intent,
            signals=NormalizedSignals(
                subject_type="event",
                pattern="prep",
                duration="one_shot",
                surface_intent="interrupt",
                domain="work",
                urgency="medium",
                subject_name=raw_intent[:60],
            ),
        )
        timings.append(StageTiming("normalize", (time.perf_counter() - t0) * 1000))

        retrieved: list[Retrieved] = []
        timings.append(StageTiming("retrieve", 0.0))

        t0 = time.perf_counter()
        authored = await author_spec(normalized, user_context, retrieved=retrieved, k=k)
        timings.append(StageTiming("author", (time.perf_counter() - t0) * 1000))

        t0 = time.perf_counter()
        preview = dry_run(authored.spec, user_id=user_context.user_id)
        timings.append(StageTiming("dry_run", (time.perf_counter() - t0) * 1000))

        return PipelineResult(
            raw_intent=raw_intent,
            normalized=normalized,
            retrieved=tuple(retrieved),
            authored=authored,
            preview=preview,
            timings=tuple(timings),
        )

    # E1: replace LLM normalize with deterministic heuristic.
    t0 = time.perf_counter()
    normalized = _heuristic_normalize(raw_intent)
    timings.append(StageTiming("normalize", (time.perf_counter() - t0) * 1000))

    t0 = time.perf_counter()
    retrieved = retrieve_top_k(raw_intent, k=k)
    timings.append(StageTiming("retrieve", (time.perf_counter() - t0) * 1000))

    t0 = time.perf_counter()
    authored = await author_spec(normalized, user_context, retrieved=retrieved, k=k)
    timings.append(StageTiming("author", (time.perf_counter() - t0) * 1000))

    t0 = time.perf_counter()
    preview = dry_run(authored.spec, user_id=user_context.user_id)
    timings.append(StageTiming("dry_run", (time.perf_counter() - t0) * 1000))

    return PipelineResult(
        raw_intent=raw_intent,
        normalized=normalized,
        retrieved=tuple(retrieved),
        authored=authored,
        preview=preview,
        timings=tuple(timings),
    )
