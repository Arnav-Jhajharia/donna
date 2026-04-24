from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.memory.retrieval.structured_hints import detect_structured_hints
from backend.memory.retrieval.types import RetrievalResult


def test_detects_expense_period_from_original_message():
    hints = detect_structured_hints(
        "how much did I spend this week",
        ["weekly expenses"],
    )

    assert hints.wants_observations is True
    assert hints.observation_type == "expense"
    assert hints.period == "this_week"


def test_original_period_wins_over_expansion_period_noise():
    hints = detect_structured_hints(
        "how much did I spend this week",
        ["today's expenses", "coffee spend today"],
    )

    assert hints.period == "this_week"


def test_detects_open_loop_and_situation_questions():
    loops = detect_structured_hints("what am i forgetting")
    brief = detect_structured_hints("what's going on with my week")

    assert loops.wants_open_loops is True
    assert brief.wants_situation_brief is True


@pytest.mark.asyncio
async def test_fanout_passes_original_message_to_structured_observation_lane(monkeypatch):
    from backend.memory.retrieval import fanout as fanout_mod

    captured = {}

    async def fake_observations(user_id, query, hints, limit):
        captured["user_id"] = user_id
        captured["query"] = query
        captured["hints"] = hints
        captured["limit"] = limit
        return [
            RetrievalResult(
                id="obs:summary:test",
                source="observations",
                content="expense observations this_week: total 6 USD",
                score=1.2,
                retrieved_via=query,
            )
        ]

    monkeypatch.setattr(fanout_mod, "_search_observations", fake_observations)

    results = await fanout_mod.fanout(
        user_id="user-1",
        queries=["weekly expenses"],
        original_message="how much did I spend this week",
        use_supermemory=False,
        use_graphiti=False,
        use_open_loops=False,
        use_situation_brief=False,
    )

    assert results[0].source == "observations"
    assert captured["query"] == "how much did I spend this week"
    assert captured["hints"].observation_type == "expense"
    assert captured["hints"].period == "this_week"


def test_observation_aggregate_sums_expenses_by_currency():
    from backend.memory.retrieval.fanout import _aggregate_observations

    rows = [
        SimpleNamespace(type="expense", fields={"amount": 6, "currency": "USD"}),
        SimpleNamespace(type="expense", fields={"amount_usd": 12}),
        SimpleNamespace(type="expense", fields={"amount": 9, "currency": "SGD"}),
    ]

    aggregate = _aggregate_observations(rows)

    assert aggregate["totals_by_currency"] == {"USD": 18.0, "SGD": 9.0}
