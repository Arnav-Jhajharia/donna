"""Tests for the proactive gates: dedup, cost, relevance."""
from __future__ import annotations

from typing import Any

import pytest

from backend.web.proactive.gates import (
    CostBudget,
    InMemoryDedupStore,
    apply_gates,
    is_obviously_bad,
)
from backend.web.proactive.types import ProactiveMove


def _move(**overrides: Any) -> ProactiveMove:
    base: dict[str, Any] = {
        "rationale": "test",
        "tool": "search",
        "query": "poke ai launch coverage 2026",
        "params": {},
        "urgency": 0.5,
        "render_hint": "short_text",
        "dedup_key": "watch:poke",
    }
    base.update(overrides)
    return ProactiveMove(**base)


# ---------------------------------------------------------------------------
# heuristic relevance
# ---------------------------------------------------------------------------


def test_obviously_bad_empty_query():
    assert is_obviously_bad(_move(query="   ")) == "empty query"


def test_obviously_bad_wellness_phrase():
    reason = is_obviously_bad(_move(query="mindfulness tips for builders"))
    assert reason and "banned phrase" in reason


def test_obviously_bad_short_search_query():
    reason = is_obviously_bad(_move(tool="search", query="ai news"))
    assert reason == "query too vague for search lane"


def test_short_query_ok_when_url():
    # If the "query" is a URL we don't impose a token-count rule.
    assert is_obviously_bad(_move(tool="search", query="https://x")) is None


def test_find_similar_requires_url_seed():
    reason = is_obviously_bad(_move(tool="find_similar", query="some article"))
    assert reason == "find_similar requires a URL seed"


def test_find_similar_url_seed_ok():
    move = _move(tool="find_similar", query="https://seed.test/a")
    assert is_obviously_bad(move) is None


def test_research_lane_skips_token_count():
    # research is expensive but not constrained by token-count heuristic.
    move = _move(tool="research", query="ai 2026")
    assert is_obviously_bad(move) is None


# ---------------------------------------------------------------------------
# in-memory dedup ledger
# ---------------------------------------------------------------------------


def test_ledger_returns_false_when_unseen():
    ledger = InMemoryDedupStore()
    assert ledger.seen("u", "key", now=0.0) is False


def test_ledger_marks_and_remembers():
    ledger = InMemoryDedupStore()
    ledger.mark("u", "key", now=100.0)
    assert ledger.seen("u", "key", now=120.0) is True


def test_ledger_expires_after_ttl():
    ledger = InMemoryDedupStore(ttl_seconds=10.0)
    ledger.mark("u", "key", now=100.0)
    assert ledger.seen("u", "key", now=109.0) is True
    assert ledger.seen("u", "key", now=111.0) is False


def test_ledger_partitioned_by_user():
    ledger = InMemoryDedupStore()
    ledger.mark("u_a", "key", now=0.0)
    assert ledger.seen("u_b", "key", now=0.0) is False


# ---------------------------------------------------------------------------
# apply_gates
# ---------------------------------------------------------------------------


def test_apply_gates_accepts_clean_moves():
    ledger = InMemoryDedupStore()
    moves = [_move(dedup_key="a"), _move(dedup_key="b")]
    outcome = apply_gates(moves, user_id="u", ledger=ledger)
    assert len(outcome.accepted) == 2
    assert outcome.dropped == []


def test_apply_gates_drops_dedup_seen():
    ledger = InMemoryDedupStore()
    ledger.mark("u", "watch:poke", now=0.0)
    moves = [_move(dedup_key="watch:poke")]
    outcome = apply_gates(moves, user_id="u", ledger=ledger, now=1.0)
    assert outcome.accepted == []
    assert outcome.dropped[0].reason == "dedup: recently fired"


def test_apply_gates_per_turn_budget():
    ledger = InMemoryDedupStore()
    moves = [_move(dedup_key=f"k{i}") for i in range(5)]
    outcome = apply_gates(
        moves,
        user_id="u",
        ledger=ledger,
        budget=CostBudget(per_turn=2, per_day=99),
    )
    assert len(outcome.accepted) == 2
    assert all(d.reason == "per-turn budget exhausted" for d in outcome.dropped)
    assert len(outcome.dropped) == 3


def test_apply_gates_per_day_budget_with_used_count():
    ledger = InMemoryDedupStore()
    moves = [_move(dedup_key=f"k{i}") for i in range(3)]
    outcome = apply_gates(
        moves,
        user_id="u",
        ledger=ledger,
        budget=CostBudget(per_turn=99, per_day=2),
        daily_used=1,  # only 1 daily slot remaining
    )
    assert len(outcome.accepted) == 1
    assert outcome.dropped[0].reason == "per-day budget exhausted"


def test_apply_gates_daily_used_at_cap_drops_all():
    ledger = InMemoryDedupStore()
    moves = [_move(dedup_key="a"), _move(dedup_key="b")]
    outcome = apply_gates(
        moves,
        user_id="u",
        ledger=ledger,
        budget=CostBudget(per_day=10),
        daily_used=10,
    )
    assert outcome.accepted == []
    assert all(d.reason == "per-day budget exhausted" for d in outcome.dropped)


def test_apply_gates_drops_relevance_failure():
    ledger = InMemoryDedupStore()
    moves = [_move(query="mindfulness tips", dedup_key="bad")]
    outcome = apply_gates(moves, user_id="u", ledger=ledger)
    assert outcome.accepted == []
    assert "banned phrase" in outcome.dropped[0].reason


def test_apply_gates_does_not_mark_ledger_on_accept():
    """Ledger marking happens after the worth-telling judge, not here."""
    ledger = InMemoryDedupStore()
    apply_gates([_move(dedup_key="watch:x")], user_id="u", ledger=ledger)
    # Nothing was marked — gates are read-only on the ledger.
    assert ledger.seen("u", "watch:x", now=0.0) is False
