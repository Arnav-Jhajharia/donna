"""Exa client unit tests — no live HTTP."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.web import client as exa


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("POST", "https://x"), response=None  # type: ignore[arg-type]
            )

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Async context manager that captures the POST and returns canned JSON."""

    def __init__(self, capture: dict[str, Any], payload: dict[str, Any]):
        self._capture = capture
        self._payload = payload

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self._capture["url"] = url
        self._capture["body"] = json
        self._capture["headers"] = headers
        return _FakeResponse(self._payload)


def _install_fake(monkeypatch, payload: dict[str, Any]) -> dict[str, Any]:
    capture: dict[str, Any] = {}

    def factory(*args, **kwargs):
        return _FakeClient(capture, payload)

    monkeypatch.setattr(exa.httpx, "AsyncClient", factory)
    return capture


@pytest.mark.asyncio
async def test_exa_search_posts_expected_body(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("poke app launch", num_results=3, search_type="neural")

    assert captured["url"] == "https://api.exa.ai/search"
    body = captured["body"]
    assert body["query"] == "poke app launch"
    assert body["numResults"] == 3
    assert body["type"] == "neural"
    # contents inline by default
    assert body["contents"]["text"] is True
    assert body["contents"]["highlights"]["numSentences"] == 3
    # headers carry api key
    assert captured["headers"]["x-api-key"] == "exa_test"


@pytest.mark.asyncio
async def test_exa_search_clamps_num_results_and_type(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", num_results=999, search_type="nonsense")
    assert captured["body"]["numResults"] == 25  # clamp cap
    assert captured["body"]["type"] == "auto"  # unknown maps to auto

    await exa.exa_search("q", num_results=0)
    assert captured["body"]["numResults"] == 1


@pytest.mark.asyncio
async def test_exa_search_passes_filters(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search(
        "q",
        category="news",
        include_domains=["techcrunch.com"],
        exclude_domains=["spam.example"],
        start_published_date="2026-01-01",
        end_published_date="2026-04-25",
    )
    body = captured["body"]
    assert body["category"] == "news"
    assert body["includeDomains"] == ["techcrunch.com"]
    assert body["excludeDomains"] == ["spam.example"]
    assert body["startPublishedDate"] == "2026-01-01"
    assert body["endPublishedDate"] == "2026-04-25"


@pytest.mark.asyncio
async def test_exa_search_without_contents_skips_contents_key(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", with_contents=False)
    assert "contents" not in captured["body"]


@pytest.mark.asyncio
async def test_exa_find_similar_posts_expected_body(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_find_similar(
        "https://example.com/seed",
        num_results=4,
        exclude_source_domain=True,
    )
    assert captured["url"] == "https://api.exa.ai/findSimilar"
    body = captured["body"]
    assert body["url"] == "https://example.com/seed"
    assert body["numResults"] == 4
    assert body["excludeSourceDomain"] is True
    assert "contents" in body


@pytest.mark.asyncio
async def test_exa_contents_posts_expected_body(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_contents(["id-a", "id-b"])
    assert captured["url"] == "https://api.exa.ai/contents"
    body = captured["body"]
    assert body["ids"] == ["id-a", "id-b"]
    assert body["text"] is True
    assert body["highlights"]["numSentences"] == 3


def test_have_exa_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert exa.have_exa_key() is False
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    assert exa.have_exa_key() is True
    monkeypatch.setenv("EXA_API_KEY", "   ")
    assert exa.have_exa_key() is False


# ---------------------------------------------------------------------------
# drift fixes: deprecated/invalid values are coerced or dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exa_search_keyword_type_coerced_to_auto(monkeypatch):
    """`keyword` search-type was deprecated; client must coerce to auto."""
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", search_type="keyword")
    assert captured["body"]["type"] == "auto"


@pytest.mark.asyncio
async def test_exa_search_invalid_category_dropped(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", category="bogus")
    assert "category" not in captured["body"]


@pytest.mark.asyncio
async def test_exa_search_livecrawl_and_max_age_pass_through(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", livecrawl="preferred", max_age_hours=24)
    body = captured["body"]
    assert body["livecrawl"] == "preferred"
    assert body["maxAgeHours"] == 24


@pytest.mark.asyncio
async def test_exa_search_invalid_livecrawl_dropped(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"results": []})

    await exa.exa_search("q", livecrawl="fallback")  # deprecated value
    assert "livecrawl" not in captured["body"]


# ---------------------------------------------------------------------------
# /research — task create + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exa_research_create_posts_instructions(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"id": "task_abc"})

    out = await exa.exa_research_create(
        "compare poke vs limitless ai pitch hardware",
        output_schema={"type": "object"},
    )
    assert out == {"id": "task_abc"}
    assert captured["url"] == "https://api.exa.ai/research/v0/tasks"
    body = captured["body"]
    assert body["instructions"].startswith("compare")
    assert body["outputSchema"] == {"type": "object"}


# ---------------------------------------------------------------------------
# /websets — create + get + items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exa_webset_create_posts_search_block(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"id": "ws_1", "status": "running"})

    await exa.exa_webset_create(
        "ai wearables shipped in 2026",
        count=15,
        entity_type="company",
        criteria=[{"description": "must ship hardware"}],
        enrichments=[{"description": "extract launch date"}],
    )
    body = captured["body"]
    assert captured["url"] == "https://api.exa.ai/websets/v0/websets"
    assert body["search"]["query"].startswith("ai wearables")
    assert body["search"]["count"] == 15
    assert body["search"]["entity"] == {"type": "company"}
    assert body["search"]["criteria"] == [{"description": "must ship hardware"}]
    assert body["enrichments"] == [{"description": "extract launch date"}]


# ---------------------------------------------------------------------------
# /monitors — create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exa_monitor_create_posts_cadence_and_behavior(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    captured = _install_fake(monkeypatch, {"id": "mon_1"})

    await exa.exa_monitor_create(
        webset_id="ws_1",
        cadence="daily",
        behavior="search",
    )
    body = captured["body"]
    assert captured["url"] == "https://api.exa.ai/websets/v0/monitors"
    assert body["websetId"] == "ws_1"
    # Exa expects structured cadence + behavior objects, not strings.
    assert body["cadence"] == {"cron": "0 0 * * *", "timezone": "UTC"}
    assert body["behavior"]["type"] == "search"
    assert body["behavior"]["config"]["count"] == 5
    assert body["behavior"]["config"]["behavior"] == "append"
