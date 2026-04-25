"""Orchestrator: feed each case through a turn runner, judge the reply.

The turn runner is injectable (Protocol). In production it wraps
``donna_runtime.runner.donna_turn``; in tests it's a deterministic fake.
This keeps the harness unit-testable without an LLM or a DB.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from scripts._stress_matrix.cases import StressCase
from scripts._stress_matrix.judge import JudgeClient, JudgeContext, grade
from scripts._stress_matrix.trace import JudgeVerdict, StressTrace


@dataclass(frozen=True)
class TurnResult:
    """What a runner gives back for one case."""

    reply_body: str
    tools_called: tuple[str, ...]
    backends_hit: tuple[str, ...]
    latency_ms: dict[str, int]
    tokens: dict[str, Any]
    error: str | None = None


class TurnRunner(Protocol):
    """A function object that fires one case and returns a TurnResult."""

    async def run(self, case: StressCase, *, user_id: str) -> TurnResult: ...


async def run_matrix(
    cases: list[StressCase],
    *,
    user_id: str,
    turn_runner: TurnRunner,
    judge_client: JudgeClient | None,
    concurrency: int = 1,
) -> list[StressTrace]:
    """Run every case. Sequential by default; ``concurrency > 1`` fans out.

    When ``judge_client`` is ``None`` we auto-verdict as ``passed=False``
    with a ``judge skipped`` reason. Useful for --dry-run and for pre-API
    wiring checks.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(case: StressCase) -> StressTrace:
        async with sem:
            try:
                turn = await turn_runner.run(case, user_id=user_id)
            except Exception as exc:  # noqa: BLE001 — boundary catch
                return _error_trace(case, f"turn_runner raised: {exc!r}")
            verdict = await _judge(case, turn, judge_client)
            return StressTrace(
                query_id=case.id,
                section=case.section,
                query=case.query,
                reply_body=turn.reply_body,
                tools_called=turn.tools_called,
                backends_hit=turn.backends_hit,
                expected_backends=case.expected_backends,
                latency_ms=turn.latency_ms,
                tokens=turn.tokens,
                judge=verdict,
                error=turn.error,
            )

    return list(await asyncio.gather(*(_one(c) for c in cases)))


async def _judge(
    case: StressCase,
    turn: TurnResult,
    client: JudgeClient | None,
) -> JudgeVerdict:
    if client is None:
        return JudgeVerdict(
            passed=False,
            reason="judge skipped (no client)",
            rubric=case.pass_criteria,
        )
    ctx = JudgeContext(case=case, reply_body=turn.reply_body, backends_hit=turn.backends_hit)
    try:
        return await grade(client, ctx)
    except Exception as exc:  # noqa: BLE001 — judge errors must not abort the run
        return JudgeVerdict(
            passed=False,
            reason=f"judge raised: {exc!r}",
            rubric=case.pass_criteria,
        )


def _error_trace(case: StressCase, error: str) -> StressTrace:
    return StressTrace(
        query_id=case.id,
        section=case.section,
        query=case.query,
        reply_body="",
        tools_called=(),
        backends_hit=(),
        expected_backends=case.expected_backends,
        latency_ms={},
        tokens={},
        judge=JudgeVerdict(passed=False, reason=error, rubric=case.pass_criteria),
        error=error,
    )
