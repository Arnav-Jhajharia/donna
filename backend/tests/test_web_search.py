"""Unit tests for the web search backend.

``search_web`` exercises the Exa path (mocked via ``backend.web.client.exa_search``).
``agentic_search`` exercises the Tavily baseline (mocked via ``_call_tavily``).
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.web import search as web


# ---------------------------------------------------------------------------
# Exa-backed search_web
# ---------------------------------------------------------------------------


def _canned_exa(*, with_highlights: bool = True) -> dict[str, Any]:
    return {
        "results": [
            {
                "id": "https://a.test",
                "url": "https://a.test",
                "title": "Result 1",
                "score": 0.9,
                "highlights": ["first highlight about X", "second highlight"]
                if with_highlights
                else [],
                "text": "a very long full text body " * 30,
            },
            {
                "id": "https://b.test",
                "url": "https://b.test",
                "title": "Result 2",
                "score": 0.85,
                "highlights": [] if with_highlights else [],
                "text": "second page body",
            },
        ],
    }


def _install_fake_exa(monkeypatch, canned: dict[str, Any] | Exception) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake(query, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        if isinstance(canned, Exception):
            raise canned
        return canned

    monkeypatch.setattr(web, "exa_search", fake)
    return captured


@pytest.mark.asyncio
async def test_search_web_missing_key_degrades(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    result = await web.search_web("anything")
    assert result["status"] == "degraded"
    assert "EXA_API_KEY" in result["payload"]["reason"]


@pytest.mark.asyncio
async def test_search_web_empty_query_is_no_hits(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    result = await web.search_web("   ")
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_search_web_returns_hits_from_highlights(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake_exa(monkeypatch, _canned_exa(with_highlights=True))

    result = await web.search_web("hello world", max_results=2)

    assert captured["query"] == "hello world"
    assert captured["kwargs"]["num_results"] == 2
    assert captured["kwargs"]["search_type"] == "auto"
    assert captured["kwargs"]["with_contents"] is True

    assert result["status"] == "ok"
    hits = result["payload"]
    assert len(hits) == 2
    assert hits[0]["title"] == "Result 1"
    assert hits[0]["url"] == "https://a.test"
    # highlights joined with " … " ellipsis; falls back to text when empty
    assert "first highlight about X" in hits[0]["snippet"]
    assert "…" in hits[0]["snippet"]
    # second result had no highlights, falls through to text
    assert hits[1]["snippet"].startswith("second page body")


@pytest.mark.asyncio
async def test_search_web_clamps_max_results(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake_exa(monkeypatch, {"results": []})

    await web.search_web("q", max_results=999)
    assert captured["kwargs"]["num_results"] == 10  # search.py clamp cap (not exa client cap)

    await web.search_web("q", max_results=0)
    assert captured["kwargs"]["num_results"] == 1


@pytest.mark.asyncio
async def test_search_web_recency_maps_to_start_published_date(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake_exa(monkeypatch, {"results": []})

    await web.search_web("q", recency="week")
    assert captured["kwargs"]["start_published_date"] is not None
    assert len(captured["kwargs"]["start_published_date"]) == 10  # YYYY-MM-DD

    await web.search_web("q", recency="decade")  # not allowed
    assert captured["kwargs"]["start_published_date"] is None


@pytest.mark.asyncio
async def test_search_web_empty_results_is_no_hits(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    _install_fake_exa(monkeypatch, {"results": []})
    result = await web.search_web("obscure query")
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_search_web_http_error_degrades(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    _install_fake_exa(monkeypatch, httpx.ReadTimeout("timeout"))
    result = await web.search_web("q")
    assert result["status"] == "degraded"
    assert "provider" in result["payload"]["reason"]


@pytest.mark.asyncio
async def test_search_web_drops_results_without_url(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    _install_fake_exa(
        monkeypatch,
        {
            "results": [
                {"title": "No url", "url": "", "highlights": ["h"]},
                {"title": "Good", "url": "https://good.test", "text": "body"},
            ]
        },
    )
    result = await web.search_web("q")
    assert result["status"] == "ok"
    assert len(result["payload"]) == 1
    assert result["payload"][0]["url"] == "https://good.test"


# ---------------------------------------------------------------------------
# Tavily-backed agentic_search (baseline for eval)
# ---------------------------------------------------------------------------


def _canned_advanced() -> dict[str, Any]:
    return {
        "answer": "Short synthesized answer.",
        "results": [
            {"title": "Source A", "url": "https://a.test", "content": "x"},
            {"title": "Source B", "url": "https://b.test", "content": "y"},
        ],
    }


@pytest.mark.asyncio
async def test_agentic_search_returns_answer_and_sources(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "sk_test")

    async def fake_call(payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["search_depth"] == "advanced"
        assert payload["include_answer"] is True
        return _canned_advanced()

    monkeypatch.setattr(web, "_call_tavily", fake_call)
    result = await web.agentic_search("compare x and y")
    assert result["status"] == "ok"
    payload = result["payload"]
    assert payload["answer"] == "Short synthesized answer."
    assert len(payload["sources"]) == 2
    assert payload["sources"][0]["url"] == "https://a.test"


@pytest.mark.asyncio
async def test_agentic_search_missing_key_degrades(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = await web.agentic_search("anything")
    assert result["status"] == "degraded"


@pytest.mark.asyncio
async def test_agentic_search_empty_is_no_hits(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "sk_test")

    async def fake_call(payload: dict[str, Any]) -> dict[str, Any]:
        return {"answer": "", "results": []}

    monkeypatch.setattr(web, "_call_tavily", fake_call)
    result = await web.agentic_search("nothing findable")
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_agentic_search_answer_only_is_ok(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "sk_test")

    async def fake_call(payload: dict[str, Any]) -> dict[str, Any]:
        return {"answer": "Just the answer.", "results": []}

    monkeypatch.setattr(web, "_call_tavily", fake_call)
    result = await web.agentic_search("q")
    assert result["status"] == "ok"
    assert result["payload"]["answer"] == "Just the answer."
    assert result["payload"]["sources"] == []
