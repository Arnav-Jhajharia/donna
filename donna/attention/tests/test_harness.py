"""Harness tests: end-to-end pipeline on 3 representative intents."""
from __future__ import annotations

import asyncio

import pytest

from donna.attention.harness import run_attention_pipeline
from donna.attention.normalize import UserContext


INTENTS = [
    "keep an eye on Poke",
    "remind me 2 hours before any flight",
    "summarize my week every Friday evening",
]


@pytest.mark.unit
@pytest.mark.parametrize("raw", INTENTS)
def test_pipeline_end_to_end(raw, monkeypatch):
    # Force LLM stages to fall back so tests don't hit the network.
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "backend.memory.retrieval.structured.call_structured", fake_none
    )

    result = asyncio.run(
        run_attention_pipeline(raw, UserContext(user_id="u1"))
    )
    assert result.raw_intent == raw
    assert result.authored.spec.title
    assert result.preview.rendered_markdown
    stages = [t.stage for t in result.timings]
    assert stages == ["normalize", "retrieve", "author", "dry_run"]
