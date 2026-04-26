"""Web search backends for Donna.

Two functions, two providers — chosen to match how they're used:

- ``search_web`` — one-shot lookup, now backed by **Exa** (neural+keyword
  auto, inline content highlights). Returns raw hits for Donna to synthesize
  in her voice.
- ``agentic_search`` — provider-side synthesis, still backed by **Tavily**
  (``search_depth=advanced`` with ``include_answer=True``). Kept as the
  eval baseline while the Exa-based ``research`` pipeline is under test.

Both degrade gracefully (``status=degraded``) when their respective API
key is unset or the HTTP call fails. Neither raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from backend.web.client import exa_search

logger = logging.getLogger(__name__)


_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT_S = 10.0
_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS_CAP = 10
_MAX_QUERY_CHARS = 400
_MAX_SNIPPET_CHARS = 500
_MAX_SOURCES = 5
_ALLOWED_RECENCY = frozenset({"day", "week", "month", "year"})
_RECENCY_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def _tavily_key() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip()


def _coerce_query(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    return q[:_MAX_QUERY_CHARS]


def _clamp_max_results(value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = _DEFAULT_MAX_RESULTS
    return max(1, min(n, _MAX_RESULTS_CAP))


def _recency_start_date(recency: str | None) -> str | None:
    if recency not in _RECENCY_DAYS:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENCY_DAYS[recency])
    return cutoff.date().isoformat()


def _exa_snippet(result: dict[str, Any]) -> str:
    highlights = result.get("highlights") or []
    if isinstance(highlights, list) and highlights:
        joined = " … ".join(str(h).strip() for h in highlights[:3] if str(h).strip())
        if joined:
            return joined[:_MAX_SNIPPET_CHARS]
    text = result.get("text") or result.get("summary") or ""
    return str(text).strip()[:_MAX_SNIPPET_CHARS]


def _format_exa_hits(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for r in results:
        url = str(r.get("url", "")).strip()
        if not url:
            continue
        title = str(r.get("title", "")).strip() or url
        snippet = _exa_snippet(r)
        hits.append({"title": title, "url": url, "snippet": snippet})
    return hits


def _format_tavily_sources(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for r in results:
        url = str(r.get("url", "")).strip()
        if not url:
            continue
        title = str(r.get("title", "")).strip() or url
        sources.append({"title": title, "url": url})
    return sources[:_MAX_SOURCES]


async def _call_tavily(payload: dict[str, Any]) -> dict[str, Any]:
    """Thin POST to Tavily. Isolated so tests can monkey-patch one seam."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
        response = await client.post(_TAVILY_ENDPOINT, json=payload)
        response.raise_for_status()
        return response.json()


async def search_web(
    query: str,
    *,
    max_results: int = _DEFAULT_MAX_RESULTS,
    recency: str | None = None,
) -> ToolResult:
    """Single-shot Exa search with inline content highlights.

    ``recency`` maps to an Exa ``startPublishedDate`` cutoff: day/week/
    month/year — anything else is ignored.
    """
    if not os.environ.get("EXA_API_KEY", "").strip():
        return degraded("EXA_API_KEY not set")
    q = _coerce_query(query)
    if not q:
        return no_hits()
    num = _clamp_max_results(max_results)
    start_date = _recency_start_date(recency) if recency in _ALLOWED_RECENCY else None
    try:
        data = await exa_search(
            q,
            num_results=num,
            search_type="auto",
            start_published_date=start_date,
            with_contents=True,
        )
    except httpx.HTTPError as exc:
        logger.warning("search_web: exa call failed: %s", exc)
        return degraded("web search provider error")
    except Exception:
        logger.exception("search_web: unexpected failure")
        return degraded("web search unavailable")
    hits = _format_exa_hits(list(data.get("results") or []))
    if not hits:
        return no_hits()
    return ok(hits)


async def agentic_search(
    question: str,
    *,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> ToolResult:
    """Provider-side agentic search via Tavily. Returns ``{answer, sources}``.

    Retained as the eval baseline against the Exa-backed ``research`` pipeline.
    """
    api_key = _tavily_key()
    if not api_key:
        return degraded("TAVILY_API_KEY not set")
    q = _coerce_query(question)
    if not q:
        return no_hits()
    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": q,
        "search_depth": "advanced",
        "include_answer": True,
        "max_results": _clamp_max_results(max_results),
    }
    try:
        data = await _call_tavily(payload)
    except httpx.HTTPError as exc:
        logger.warning("agentic_search: tavily call failed: %s", exc)
        return degraded("web search provider error")
    except Exception:
        logger.exception("agentic_search: unexpected failure")
        return degraded("web search unavailable")
    answer = str(data.get("answer") or "").strip()
    sources = _format_tavily_sources(list(data.get("results") or []))
    if not answer and not sources:
        return no_hits()
    return ok({"answer": answer, "sources": sources})
