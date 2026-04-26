"""End-to-end tests for the proactive runner.

All seams are mocked — query_creation, executor, judge, and the profile
loader. We never hit Exa, Anthropic, or the DB.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.web.proactive import runner as runner_mod
from backend.web.proactive.gates import (
    CostBudget,
    GateDrop,
    GateOutcome,
    InMemoryDedupStore,
)
from backend.web.proactive.judge import JudgeVerdict
from backend.web.proactive.runner import (
    ProactiveTickResult,
    build_context,
    run_proactive_tick,
)
from backend.web.proactive.types import (
    ProactiveContext,
    ProactiveMove,
    ProactiveResult,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _move(**overrides: Any) -> ProactiveMove:
    base: dict[str, Any] = {
        "rationale": "test",
        "tool": "search",
        "query": "poke v2 launch coverage 2026",
        "params": {},
        "urgency": 0.7,
        "render_hint": "short_text",
        "dedup_key": "watch:poke",
    }
    base.update(overrides)
    return ProactiveMove(**base)


def _result(move: ProactiveMove, status: str = "ok") -> ProactiveResult:
    return ProactiveResult(
        move=move,
        status=status,  # type: ignore[arg-type]
        payload={"results": [{"url": "https://a.test", "title": "A"}]},
        elapsed_ms=50,
    )


async def _fake_blurb(user_id: str) -> str:
    return f"USER MODEL\nuser_id={user_id}\nuser is building donna"


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_context_uses_loader_and_stamps_time():
    ctx = await build_context(
        "u_test",
        recent_thread="user: hi",
        last_proactive_at="2026-04-25T09:00:00",
        load_blurb=_fake_blurb,
    )
    assert ctx.user_id == "u_test"
    assert "USER MODEL" in ctx.profile_blurb
    assert ctx.recent_thread == "user: hi"
    assert ctx.last_proactive_at == "2026-04-25T09:00:00"
    assert ctx.current_datetime  # ISO string was set


# ---------------------------------------------------------------------------
# run_proactive_tick — full happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_full_flow_send_marks_ledger(monkeypatch):
    moves = [_move(dedup_key="watch:poke")]
    results = [_result(moves[0])]
    verdicts = [(results[0], JudgeVerdict(decision="send", draft="poke v2 shipped"))]

    async def fake_create(ctx, **kwargs):
        return moves

    async def fake_exec(accepted):
        return results

    async def fake_judge(*, context, results):
        return verdicts

    monkeypatch.setattr(runner_mod, "create_proactive_moves", fake_create)
    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    ledger = InMemoryDedupStore()
    out = await run_proactive_tick(
        user_id="u",
        ledger=ledger,
        load_blurb=_fake_blurb,
    )
    assert isinstance(out, ProactiveTickResult)
    assert out.moves_emitted == moves
    assert out.moves_dropped == []
    assert len(out.verdicts) == 1
    assert out.drafts_to_send == [(results[0], "poke v2 shipped")]
    # ledger marked for the sent move
    assert ledger.seen("u", "watch:poke", now=0.0) is True


@pytest.mark.asyncio
async def test_tick_silence_does_not_mark_ledger(monkeypatch):
    moves = [_move(dedup_key="watch:poke")]
    results = [_result(moves[0])]
    verdicts = [(results[0], JudgeVerdict(decision="silence", reason="stale"))]

    monkeypatch.setattr(runner_mod, "create_proactive_moves", lambda c, **k: _async(moves))
    monkeypatch.setattr(runner_mod, "execute_moves", lambda a: _async(results))
    monkeypatch.setattr(runner_mod, "judge_results", lambda **k: _async(verdicts))

    ledger = InMemoryDedupStore()
    out = await run_proactive_tick(user_id="u", ledger=ledger, load_blurb=_fake_blurb)
    assert out.drafts_to_send == []
    # Silenced moves should NOT burn the dedup slot.
    assert ledger.seen("u", "watch:poke", now=0.0) is False


# ---------------------------------------------------------------------------
# zero moves — short-circuit before any execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_zero_moves_short_circuits(monkeypatch):
    exec_called = {"v": False}
    judge_called = {"v": False}

    async def fake_create(ctx, **kwargs):
        return []

    async def fake_exec(_):
        exec_called["v"] = True
        return []

    async def fake_judge(**kwargs):
        judge_called["v"] = True
        return []

    monkeypatch.setattr(runner_mod, "create_proactive_moves", fake_create)
    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    out = await run_proactive_tick(user_id="u", load_blurb=_fake_blurb)
    assert out.moves_emitted == []
    assert out.results == []
    assert exec_called["v"] is False
    assert judge_called["v"] is False


# ---------------------------------------------------------------------------
# all-gated — moves emitted but every one dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_all_gated_short_circuits_execution(monkeypatch):
    moves = [_move(dedup_key="watch:poke")]
    exec_called = {"v": False}

    monkeypatch.setattr(runner_mod, "create_proactive_moves", lambda c, **k: _async(moves))

    async def fake_exec(_):
        exec_called["v"] = True
        return []

    async def fake_judge(**k):
        return []

    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    # Pre-load the ledger so the only move dedups out. Use wall-clock
    # time because apply_gates compares against time.time() internally.
    import time as _time

    ledger = InMemoryDedupStore()
    ledger.mark("u", "watch:poke", now=_time.time())

    out = await run_proactive_tick(user_id="u", ledger=ledger, load_blurb=_fake_blurb)
    assert out.moves_emitted == moves
    assert len(out.moves_dropped) == 1
    assert "dedup" in out.moves_dropped[0].reason
    assert out.results == []
    assert exec_called["v"] is False


# ---------------------------------------------------------------------------
# context-build failure — never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_context_build_failure_returns_empty(monkeypatch):
    async def boom(user_id):
        raise RuntimeError("db down")

    out = await run_proactive_tick(user_id="u", load_blurb=boom)
    assert out.moves_emitted == []
    assert out.results == []


# ---------------------------------------------------------------------------
# budget threading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_passes_budget_through_to_gates(monkeypatch):
    moves = [_move(dedup_key=f"k{i}") for i in range(5)]
    monkeypatch.setattr(runner_mod, "create_proactive_moves", lambda c, **k: _async(moves))

    captured: dict[str, Any] = {}

    async def fake_exec(accepted):
        captured["accepted_count"] = len(accepted)
        return [_result(m) for m in accepted]

    async def fake_judge(**kwargs):
        return [
            (r, JudgeVerdict(decision="silence", reason="ok"))
            for r in kwargs["results"]
        ]

    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    out = await run_proactive_tick(
        user_id="u",
        ledger=InMemoryDedupStore(),
        budget=CostBudget(per_turn=2, per_day=99),
        load_blurb=_fake_blurb,
    )
    assert captured["accepted_count"] == 2
    assert len(out.moves_dropped) == 3


# ---------------------------------------------------------------------------
# helper: run an awaitable with a non-coroutine return (lambda factories)
# ---------------------------------------------------------------------------


async def _async(value):
    return value
