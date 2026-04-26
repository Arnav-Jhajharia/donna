"""Tests for the proactive executor.

All Exa client calls are monkey-patched via the rebound names in
``backend.web.proactive.executor``. We never hit the network.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.web.proactive import executor as ex
from backend.web.proactive.types import ProactiveMove


def _move(**overrides: Any) -> ProactiveMove:
    base: dict[str, Any] = {
        "rationale": "test",
        "tool": "search",
        "query": "poke ai launch",
        "params": {},
        "urgency": 0.5,
        "render_hint": "short_text",
        "dedup_key": "watch:poke",
    }
    base.update(overrides)
    return ProactiveMove(**base)


# ---------------------------------------------------------------------------
# missing api key short-circuits to skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skipped_when_no_api_key(monkeypatch):
    monkeypatch.setattr(ex, "have_exa_key", lambda: False)
    result = await ex.execute_move(_move())
    assert result.status == "skipped"
    assert result.skipped_reason == "no exa api key"


# ---------------------------------------------------------------------------
# search lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_dispatches_with_params(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {"results": [{"url": "https://a.test", "title": "A"}]}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_search", fake)

    move = _move(
        tool="search",
        params={
            "category": "company",
            "maxAgeHours": 12,
            "livecrawl": "preferred",
            "includeDomains": ["techcrunch.com"],
        },
    )
    result = await ex.execute_move(move)
    assert result.status == "ok"
    assert captured["query"] == "poke ai launch"
    assert captured["category"] == "company"
    assert captured["max_age_hours"] == 12
    assert captured["livecrawl"] == "preferred"
    assert captured["include_domains"] == ["techcrunch.com"]


@pytest.mark.asyncio
async def test_search_no_results_returns_no_hits(monkeypatch):
    async def fake(query, **kwargs):
        return {"results": []}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_search", fake)

    result = await ex.execute_move(_move())
    assert result.status == "no_hits"


@pytest.mark.asyncio
async def test_search_exception_collapses_to_degraded(monkeypatch):
    async def boom(query, **kwargs):
        raise RuntimeError("exa 503")

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_search", boom)

    result = await ex.execute_move(_move())
    assert result.status == "degraded"
    assert "exa 503" in (result.skipped_reason or "")


# ---------------------------------------------------------------------------
# find_similar lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_similar_uses_query_as_seed_url(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {"results": [{"url": "https://similar.test"}]}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_find_similar", fake)

    move = _move(
        tool="find_similar",
        query="https://seed.test/article",
        params={"excludeSourceDomain": True},
    )
    result = await ex.execute_move(move)
    assert result.status == "ok"
    assert captured["url"] == "https://seed.test/article"
    assert captured["exclude_source_domain"] is True


# ---------------------------------------------------------------------------
# research lane (returns task id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_returns_task_id(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake(instructions, **kwargs):
        captured["instructions"] = instructions
        captured.update(kwargs)
        return {"id": "task_xyz"}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_research_create", fake)

    move = _move(
        tool="research",
        query="how have ai pitch hardware tools evolved 2024-2026",
        params={"outputSchema": {"type": "object"}},
    )
    result = await ex.execute_move(move)
    assert result.status == "ok"
    assert result.payload == {"id": "task_xyz"}
    assert captured["output_schema"] == {"type": "object"}


# ---------------------------------------------------------------------------
# webset lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webset_create_passes_count_and_criteria(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {"id": "ws_42", "status": "running"}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_webset_create", fake)

    move = _move(
        tool="webset",
        query="ai wearables that shipped hardware in 2026",
        params={
            "count": 20,
            "entityType": "company",
            "criteria": [{"description": "must ship hw"}],
        },
    )
    result = await ex.execute_move(move)
    assert result.status == "ok"
    assert result.payload["id"] == "ws_42"
    assert captured["count"] == 20
    assert captured["entity_type"] == "company"
    assert captured["criteria"] == [{"description": "must ship hw"}]


# ---------------------------------------------------------------------------
# monitor lane (requires websetId)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_requires_webset_id(monkeypatch):
    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    move = _move(tool="monitor", query="watch competitors", params={})
    result = await ex.execute_move(move)
    assert result.status == "degraded"
    assert "websetId" in (result.skipped_reason or "")


@pytest.mark.asyncio
async def test_monitor_create_passes_cadence_and_behavior(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake(*, webset_id, cadence, behavior, **kwargs):
        captured["webset_id"] = webset_id
        captured["cadence"] = cadence
        captured["behavior"] = behavior
        return {"id": "mon_99"}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_monitor_create", fake)

    move = _move(
        tool="monitor",
        query="poke release notifications",
        params={"websetId": "ws_42", "cadence": "hourly", "behavior": "search"},
    )
    result = await ex.execute_move(move)
    assert result.status == "ok"
    assert captured == {
        "webset_id": "ws_42",
        "cadence": "hourly",
        "behavior": "search",
    }


# ---------------------------------------------------------------------------
# unknown tool -> skipped (defense in depth; reasoner already validates)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_skipped(monkeypatch):
    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    # Bypass dataclass Literal check by reaching into __dict__ via object.__setattr__.
    move = _move()
    object.__setattr__(move, "tool", "telepathy")
    result = await ex.execute_move(move)
    assert result.status == "skipped"
    assert "unknown tool" in (result.skipped_reason or "")


# ---------------------------------------------------------------------------
# execute_moves preserves order and never crashes on per-move failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_moves_preserves_order_and_isolates_failure(monkeypatch):
    call_log: list[str] = []

    async def fake_search(query, **kwargs):
        call_log.append(query)
        if "broken" in query:
            raise RuntimeError("lane down")
        return {"results": [{"url": "https://a.test"}]}

    monkeypatch.setattr(ex, "have_exa_key", lambda: True)
    monkeypatch.setattr(ex, "exa_search", fake_search)

    moves = [
        _move(query="alpha", dedup_key="a"),
        _move(query="broken", dedup_key="b"),
        _move(query="gamma", dedup_key="c"),
    ]
    results = await ex.execute_moves(moves)
    assert [r.move.dedup_key for r in results] == ["a", "b", "c"]
    assert results[0].status == "ok"
    assert results[1].status == "degraded"
    assert results[2].status == "ok"
