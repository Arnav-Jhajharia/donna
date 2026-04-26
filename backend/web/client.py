"""Thin httpx client for the Exa Search API.

One module for Exa's three endpoints we use:

- ``/search`` with optional ``contents`` body (one round-trip for search + text)
- ``/findSimilar`` for semantic nearest-neighbor on a seed URL
- ``/contents`` for fetching full text / highlights on known ids

All functions return the parsed JSON verbatim and raise ``httpx.HTTPError``
on network / 4xx / 5xx failures. Higher layers are responsible for mapping
those to ``status=degraded`` — we stay close to the wire.

Degrades gracefully on a missing ``EXA_API_KEY``: the ``have_exa_key()``
probe lets callers decide before building a request.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EXA_BASE = "https://api.exa.ai"
_DEFAULT_TIMEOUT_S = 12.0
_MAX_NUM_RESULTS = 25

# Exa search types per https://exa.ai/docs/llms.txt as of 2026-04-25.
# `keyword` is deprecated — coerce to `auto` so callers don't need to know.
_VALID_SEARCH_TYPES: frozenset[str] = frozenset(
    {"auto", "neural", "fast"}
)

# Exa livecrawl values per https://exa.ai/docs/llms.txt as of 2026-04-25.
_VALID_LIVECRAWL: frozenset[str] = frozenset(
    {"always", "never", "preferred"}
)

# Exa categories per https://exa.ai/docs/llms.txt as of 2026-04-25.
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {"company", "people", "news", "code"}
)


_DEFAULT_HIGHLIGHTS = {
    "numSentences": 3,
    "highlightsPerUrl": 3,
}


def have_exa_key() -> bool:
    return bool(os.environ.get("EXA_API_KEY", "").strip())


def _api_key() -> str:
    return os.environ.get("EXA_API_KEY", "").strip()


def _headers() -> dict[str, str]:
    return {
        "x-api-key": _api_key(),
        "accept": "application/json",
        "content-type": "application/json",
    }


def _clamp_num(num: int) -> int:
    try:
        n = int(num)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(n, _MAX_NUM_RESULTS))


async def _post(path: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{_EXA_BASE}{path}",
            json=body,
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def exa_search(
    query: str,
    *,
    num_results: int = 5,
    search_type: str = "auto",
    category: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    start_published_date: str | None = None,
    end_published_date: str | None = None,
    livecrawl: str | None = None,
    max_age_hours: int | None = None,
    with_contents: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST /search. Returns Exa's JSON as-is.

    ``search_type`` is one of ``auto``, ``neural``, ``fast``. ``keyword``
    has been deprecated by Exa and is silently coerced to ``auto``. When
    ``with_contents`` is True the request asks Exa to inline text
    highlights so we skip the separate /contents round-trip.
    """
    body: dict[str, Any] = {
        "query": query,
        "numResults": _clamp_num(num_results),
        "type": search_type if search_type in _VALID_SEARCH_TYPES else "auto",
    }
    if category and category in _VALID_CATEGORIES:
        body["category"] = category
    if include_domains:
        body["includeDomains"] = list(include_domains)
    if exclude_domains:
        body["excludeDomains"] = list(exclude_domains)
    if start_published_date:
        body["startPublishedDate"] = start_published_date
    if end_published_date:
        body["endPublishedDate"] = end_published_date
    if livecrawl and livecrawl in _VALID_LIVECRAWL:
        body["livecrawl"] = livecrawl
    if max_age_hours is not None:
        try:
            body["maxAgeHours"] = max(1, int(max_age_hours))
        except (TypeError, ValueError):
            pass
    if with_contents:
        body["contents"] = {"text": True, "highlights": _DEFAULT_HIGHLIGHTS}
    return await _post("/search", body, timeout=timeout)


async def exa_find_similar(
    url: str,
    *,
    num_results: int = 5,
    with_contents: bool = True,
    exclude_source_domain: bool = False,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": url,
        "numResults": _clamp_num(num_results),
    }
    if exclude_source_domain:
        body["excludeSourceDomain"] = True
    if with_contents:
        body["contents"] = {"text": True, "highlights": _DEFAULT_HIGHLIGHTS}
    return await _post("/findSimilar", body, timeout=timeout)


async def exa_contents(
    ids: list[str],
    *,
    text: bool = True,
    highlights: bool = True,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    body: dict[str, Any] = {"ids": list(ids)}
    if text:
        body["text"] = True
    if highlights:
        body["highlights"] = _DEFAULT_HIGHLIGHTS
    return await _post("/contents", body, timeout=timeout)


# ---------------------------------------------------------------------------
# /research — async multi-step synthesis. Task-based: create then poll.
# ---------------------------------------------------------------------------


async def exa_research_create(
    instructions: str,
    *,
    output_schema: dict[str, Any] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST /research/v0/tasks. Returns ``{"id": "..."}``.

    The task runs server-side. Poll ``exa_research_get`` to retrieve.
    ``output_schema`` is an optional JSON schema constraining the result.
    """
    body: dict[str, Any] = {"instructions": instructions}
    if output_schema:
        body["outputSchema"] = output_schema
    return await _post("/research/v0/tasks", body, timeout=timeout)


async def exa_research_get(
    task_id: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET /research/v0/tasks/{id}. Returns status + result when ready."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{_EXA_BASE}/research/v0/tasks/{task_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# /websets — persistent, auto-verified curated sets.
# ---------------------------------------------------------------------------


async def exa_webset_create(
    search_query: str,
    *,
    count: int = 10,
    entity_type: str | None = None,
    enrichments: list[dict[str, Any]] | None = None,
    criteria: list[dict[str, Any]] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST /websets/v0/websets. Returns the new webset (id, status, ...)."""
    search_block: dict[str, Any] = {
        "query": search_query,
        "count": max(1, int(count)),
    }
    if entity_type:
        search_block["entity"] = {"type": entity_type}
    if criteria:
        search_block["criteria"] = list(criteria)
    body: dict[str, Any] = {"search": search_block}
    if enrichments:
        body["enrichments"] = list(enrichments)
    return await _post("/websets/v0/websets", body, timeout=timeout)


async def exa_webset_get(
    webset_id: str,
    *,
    expand_items: bool = False,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET /websets/v0/websets/{id}. Optionally inline current items."""
    suffix = "?expand=items" if expand_items else ""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{_EXA_BASE}/websets/v0/websets/{webset_id}{suffix}",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def exa_webset_items(
    webset_id: str,
    *,
    limit: int = 25,
    cursor: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET /websets/v0/websets/{id}/items. Paginated."""
    params = f"?limit={max(1, int(limit))}"
    if cursor:
        params += f"&cursor={cursor}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{_EXA_BASE}/websets/v0/websets/{webset_id}/items{params}",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# /monitors — recurring scheduled searches with webhook delivery.
# ---------------------------------------------------------------------------


async def exa_monitor_create(
    *,
    webset_id: str,
    cadence: str = "daily",
    behavior: str = "search",
    fields: dict[str, Any] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST /websets/v0/monitors. Schedules a recurring run on a webset.

    ``cadence`` is one of ``hourly``, ``daily``, ``weekly``, ``monthly``.
    ``behavior`` is ``search`` (find new items) or ``refresh`` (re-verify).
    """
    body: dict[str, Any] = {
        "websetId": webset_id,
        "cadence": cadence,
        "behavior": behavior,
    }
    if fields:
        body.update(fields)
    return await _post("/websets/v0/monitors", body, timeout=timeout)


async def exa_monitor_list(
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET /websets/v0/monitors. Lists all monitors."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{_EXA_BASE}/websets/v0/monitors",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def exa_monitor_delete(
    monitor_id: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """DELETE /websets/v0/monitors/{id}."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.delete(
            f"{_EXA_BASE}/websets/v0/monitors/{monitor_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json() if response.content else {"deleted": True}
