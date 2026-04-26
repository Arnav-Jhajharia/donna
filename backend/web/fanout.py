"""Parallel Exa fanout across neural, keyword, and find_similar lanes.

Mirrors ``backend.memory.retrieval.fanout.fanout``:

- each expansion query becomes one async task,
- an optional seed URL adds a ``find_similar`` lane,
- tasks race via ``asyncio.gather(return_exceptions=True)`` so one lane
  failing never takes down the pool.

Normalizes every Exa response row into a frozen ``WebHit``; downstream
merge + rerank only see ``WebHit``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.web.client import exa_find_similar, exa_search
from backend.web.types import WebExpansion, WebHit

logger = logging.getLogger(__name__)

_PER_QUERY_LIMIT = 6
_MAX_SNIPPET_CHARS = 800


async def fanout(
    *,
    expansion: WebExpansion,
    per_query_limit: int = _PER_QUERY_LIMIT,
    seed_url: str | None = None,
) -> list[WebHit]:
    tasks: list[asyncio.Task] = []
    for q in expansion.neural_queries:
        if q.strip():
            tasks.append(
                asyncio.create_task(_run_search(q, "neural", per_query_limit))
            )
    if expansion.hypothetical:
        tasks.append(
            asyncio.create_task(
                _run_search(expansion.hypothetical, "neural", per_query_limit)
            )
        )
    # Exa deprecated `keyword` search-type; route keyword-bag queries
    # through `auto` (Exa picks the right backend internally).
    for q in expansion.keyword_queries:
        if q.strip():
            tasks.append(
                asyncio.create_task(_run_search(q, "auto", per_query_limit))
            )
    if seed_url:
        tasks.append(
            asyncio.create_task(_run_find_similar(seed_url, per_query_limit))
        )

    if not tasks:
        return []
    batched = await asyncio.gather(*tasks, return_exceptions=True)
    hits: list[WebHit] = []
    for b in batched:
        if isinstance(b, Exception):
            logger.warning("web fanout lane failed: %s", b)
            continue
        hits.extend(b)
    return hits


def _hit_from_exa_result(r: dict[str, Any], *, via: str) -> WebHit | None:
    url = str(r.get("url", "")).strip()
    if not url:
        return None
    title = str(r.get("title", "")).strip() or url
    highlights = r.get("highlights") or []
    if isinstance(highlights, list) and highlights:
        snippet = " … ".join(
            str(h).strip() for h in highlights[:3] if str(h).strip()
        )
    else:
        snippet = str(r.get("text") or r.get("summary") or "").strip()
    return WebHit(
        url=url,
        title=title,
        snippet=snippet[:_MAX_SNIPPET_CHARS],
        published_date=(str(r.get("publishedDate") or "").strip() or None),
        author=(str(r.get("author") or "").strip() or None),
        score=float(r.get("score") or 0.0),
        retrieved_via=via,
        metadata={"exa_id": str(r.get("id") or "")},
    )


async def _run_search(query: str, search_type: str, num: int) -> list[WebHit]:
    try:
        data = await exa_search(
            query,
            num_results=num,
            search_type=search_type,
            with_contents=True,
        )
    except Exception as exc:
        logger.warning("fanout %s search failed: %s", search_type, exc)
        return []
    label = f"{search_type}:{query[:60]}"
    return _parse_results(data, via=label)


async def _run_find_similar(url: str, num: int) -> list[WebHit]:
    try:
        data = await exa_find_similar(url, num_results=num, with_contents=True)
    except Exception as exc:
        logger.warning("fanout find_similar failed: %s", exc)
        return []
    return _parse_results(data, via=f"find_similar:{url[:60]}")


def _parse_results(data: dict[str, Any], *, via: str) -> list[WebHit]:
    out: list[WebHit] = []
    for r in (data.get("results") or []):
        h = _hit_from_exa_result(r, via=via)
        if h:
            out.append(h)
    return out
