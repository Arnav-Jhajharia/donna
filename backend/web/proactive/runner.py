"""Proactive turn orchestrator.

Wires the five proactive stages into a single ``run_proactive_tick``:

  build_context → create_moves → apply_gates → execute → judge → mark

The runner is **deterministic glue** — it doesn't decide anything itself.
All decisions live in the layered modules:

- ``query_creation.create_proactive_moves`` decides *what* to look up
- ``gates.apply_gates`` decides *whether* a move is allowed to fire
- ``executor.execute_moves`` decides nothing; it dispatches
- ``judge.judge_results`` decides *whether the result earns a ping*

The runner returns a ``ProactiveTickResult`` with the moves emitted, the
moves dropped (with reasons), and the verdicts (``send`` / ``silence``).

Side effects:
- It calls ``ledger.mark`` for every move whose verdict is ``send`` so we
  don't fire the same intent again before TTL.
- It does **not** deliver messages — the caller decides whether to push
  the drafts onto a WhatsApp queue, log them as shadows, or surface them
  in the dashboard. Keeping delivery out of the runner means proactive
  flows are easy to dry-run.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from backend.web.proactive.executor import execute_moves
from backend.web.proactive.gates import (
    CostBudget,
    DedupStore,
    InMemoryDedupStore,
    GateDrop,
    apply_gates,
)
from backend.web.proactive.judge import JudgeVerdict, judge_results
from backend.web.proactive.query_creation import create_proactive_moves
from backend.web.proactive.types import (
    ProactiveContext,
    ProactiveMove,
    ProactiveResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# context builder
# ---------------------------------------------------------------------------


ContextLoader = Callable[[str], Awaitable[str]]
"""Returns the rendered profile blurb (USER MODEL + SITUATION BRIEF + LIVING
PROFILE merged) for a user. The default implementation calls
``backend.memory.user_facts.rendering.load_and_render``; tests inject
their own."""


async def _default_load_blurb(user_id: str) -> str:
    from backend.memory.user_facts.rendering import load_and_render

    return await load_and_render(user_id)


async def build_context(
    user_id: str,
    *,
    recent_thread: str = "",
    last_proactive_at: str | None = None,
    now: datetime | None = None,
    load_blurb: ContextLoader = _default_load_blurb,
) -> ProactiveContext:
    """Snapshot what the brain knows about the user RIGHT NOW.

    The merged Living-Profile / Situation-Brief block is dropped into
    ``profile_blurb``; the reasoner will read everything.
    """
    blurb = await load_blurb(user_id)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    return ProactiveContext(
        user_id=user_id,
        profile_blurb=blurb or "",
        situation_brief="",  # already merged into blurb
        recent_thread=recent_thread,
        current_datetime=stamp,
        last_proactive_at=last_proactive_at,
    )


# ---------------------------------------------------------------------------
# tick result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProactiveTickResult:
    """Trace-friendly summary of one proactive tick."""

    user_id: str
    moves_emitted: list[ProactiveMove]
    moves_dropped: list[GateDrop]
    results: list[ProactiveResult]
    verdicts: list[tuple[ProactiveResult, JudgeVerdict]]
    elapsed_ms: int

    @property
    def drafts_to_send(self) -> list[tuple[ProactiveResult, str]]:
        """Convenience: only the (result, draft) pairs the judge greenlit."""
        return [
            (r, v.draft) for r, v in self.verdicts if v.decision == "send" and v.draft
        ]


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


async def run_proactive_tick(
    *,
    user_id: str,
    ledger: DedupStore | None = None,
    budget: CostBudget = CostBudget(),
    daily_used: int = 0,
    recent_thread: str = "",
    last_proactive_at: str | None = None,
    max_moves: int = 3,
    load_blurb: ContextLoader = _default_load_blurb,
) -> ProactiveTickResult:
    """Run one proactive cycle for a single user. Never raises.

    The default ``ledger`` is a fresh in-memory store — fine for one-shot
    use (e.g. CLI dry-runs, tests). Long-running schedulers should pass
    in a shared, persistent ledger so dedup works across ticks.
    """
    started = time.monotonic()
    if ledger is None:
        from backend.web.proactive.store import PostgresDedupStore
        ledger = PostgresDedupStore()

    try:
        context = await build_context(
            user_id,
            recent_thread=recent_thread,
            last_proactive_at=last_proactive_at,
            load_blurb=load_blurb,
        )
    except Exception:
        logger.exception("run_proactive_tick: context build failed")
        return ProactiveTickResult(
            user_id=user_id,
            moves_emitted=[],
            moves_dropped=[],
            results=[],
            verdicts=[],
            elapsed_ms=_elapsed_ms(started),
        )

    moves = await create_proactive_moves(context, max_moves=max_moves)
    if not moves:
        return ProactiveTickResult(
            user_id=user_id,
            moves_emitted=[],
            moves_dropped=[],
            results=[],
            verdicts=[],
            elapsed_ms=_elapsed_ms(started),
        )

    outcome = await apply_gates(
        moves,
        user_id=user_id,
        ledger=ledger,
        budget=budget,
        daily_used=daily_used,
    )
    if not outcome.accepted:
        return ProactiveTickResult(
            user_id=user_id,
            moves_emitted=moves,
            moves_dropped=outcome.dropped,
            results=[],
            verdicts=[],
            elapsed_ms=_elapsed_ms(started),
        )

    results = await execute_moves(outcome.accepted)
    verdicts = await judge_results(context=context, results=results)

    # Mark dedup ledger for everything we're about to send. Silenced moves
    # don't burn the slot — the user might benefit from a fresher take on
    # the same intent next tick.
    now_ts = time.time()
    for r, v in verdicts:
        if v.decision == "send":
            await ledger.mark_async(user_id, r.move.dedup_key, now=now_ts)

    return ProactiveTickResult(
        user_id=user_id,
        moves_emitted=moves,
        moves_dropped=outcome.dropped,
        results=results,
        verdicts=verdicts,
        elapsed_ms=_elapsed_ms(started),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
