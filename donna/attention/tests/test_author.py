"""Author tests: ping short-circuit + fallback + LLM path mocked."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from donna.attention.author import (
    _looks_like_bare_reminder,
    _ping_spec,
    author_spec,
)
from donna.attention.normalize import NormalizedIntent, NormalizedSignals, UserContext
from donna.attention.retrieve import retrieve_top_k
from donna.attention.schema import AttentionSpec
from donna.attention.vocabulary import CardType, SourceType


def _normalized(raw: str) -> NormalizedIntent:
    return NormalizedIntent(
        raw_text=raw,
        normalized_text=raw,
        signals=NormalizedSignals(subject_name="thing"),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("remind me to call mom at 6pm", True),
        ("ping me in the morning", True),
        ("don't let me forget groceries", True),
        ("keep an eye on Poke", False),
        ("track my subscriptions", False),
    ],
)
def test_looks_like_bare_reminder(raw, expected):
    assert _looks_like_bare_reminder(raw) is expected


@pytest.mark.unit
def test_ping_spec_validates():
    spec = _ping_spec("remind me to call mom at 6pm", _normalized("remind me to call mom at 6pm"))
    assert isinstance(spec, AttentionSpec)
    assert spec.card is CardType.PING
    assert spec.sources[0].type is SourceType.USER_ELICITATION


@pytest.mark.unit
def test_author_ping_shortcircuit(monkeypatch):
    # Ensure the LLM path is NOT called for bare reminders
    async def fail(**kwargs):
        raise AssertionError("LLM should not be called for ping short-circuit")

    monkeypatch.setattr(
        "backend.memory.retrieval.structured.call_structured", fail
    )
    norm = _normalized("remind me to call mom at 6pm")
    result = asyncio.run(author_spec(norm, UserContext(user_id="u1")))
    assert result.via == "ping_shortcircuit"
    assert result.spec.card is CardType.PING


@pytest.mark.unit
def test_author_falls_back_when_llm_returns_none(monkeypatch):
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )
    norm = _normalized("keep an eye on Poke")
    result = asyncio.run(author_spec(norm, UserContext(user_id="u1")))
    assert result.via == "fallback"
    assert result.spec.title


@pytest.mark.unit
def test_retrieved_passed_through(monkeypatch):
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )
    hits = retrieve_top_k("keep an eye on Poke", k=3)
    norm = _normalized("keep an eye on Poke")
    result = asyncio.run(
        author_spec(norm, UserContext(user_id="u1"), retrieved=hits)
    )
    assert result.retrieved_ids == tuple(h.example.example_id for h in hits)
