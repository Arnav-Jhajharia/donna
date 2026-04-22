"""Normalize tests. LLM path mocked; heuristic path exercised."""
from __future__ import annotations

import asyncio

import pytest

from donna.attention.normalize import (
    NormalizedIntent,
    UserContext,
    _heuristic_normalize,
    normalize_intent,
)


DIVERSE_INTENTS = [
    ("keep an eye on Poke", "watch", "competitive_intel"),
    ("summarize my week every Friday evening", "brief", "work"),
    ("remind me 2 hours before any flight", "prep", "flight"),
    ("track how much I spend on subscriptions", "track", "finance"),
    ("close the loop on investor follow ups", "loop", "fundraising"),
    ("watch for any Series A news about Linear competitors", "watch", "fundraising"),
    ("brief me before my 1:1 with Sarah", "prep", "meeting"),
    ("track my sleep quality over the month", "track", "health"),
    ("follow the latest arxiv papers on RAG evaluation", "watch", "learning"),
    ("monitor shipment for tracking number 1Z999", "watch", "shipment"),
]


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_pattern,expected_domain", DIVERSE_INTENTS)
def test_heuristic_produces_signals(raw, expected_pattern, expected_domain):
    result = _heuristic_normalize(raw)
    assert isinstance(result, NormalizedIntent)
    assert result.raw_text == raw
    assert result.normalized_text  # non-empty
    assert result.signals.pattern == expected_pattern
    assert result.signals.domain == expected_domain


@pytest.mark.unit
def test_empty_intent_rejected():
    ctx = UserContext(user_id="u1")
    with pytest.raises(ValueError):
        asyncio.run(normalize_intent("   ", ctx))


@pytest.mark.unit
def test_normalize_falls_back_when_call_structured_returns_none(monkeypatch):
    async def fake_none(**kwargs):
        return None

    import donna.attention.normalize as nm

    monkeypatch.setattr(
        "backend.memory.retrieval.structured.call_structured", fake_none
    )
    result = asyncio.run(
        nm.normalize_intent("keep an eye on Poke", UserContext(user_id="u1"))
    )
    assert result.raw_text == "keep an eye on Poke"
    assert result.signals.pattern == "watch"
