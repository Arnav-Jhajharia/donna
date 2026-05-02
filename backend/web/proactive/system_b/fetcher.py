"""Webset-emulating fetcher.

Exa websets cost ~10 credits per delivered row because they verify and
enrich every item before delivery. This module provides the same
"persistent topic that finds new neighbor pages" behavior using only
``/search`` (~5 credits) and ``/findSimilar`` (~5 credits) — much cheaper
for our budget.

Algorithm per query:
  1. Run ``exa_search(query.text, num_results=3)`` — 5 credits.
  2. If ``query.expand_with_similar`` and results are present, run
     ``exa_find_similar(top_url, num_results=3)`` to surface neighbors —
     5 credits, optional.
  3. Dedupe URLs against (a) other queries in this batch and
     (b) historical signals already enqueued for this user.
  4. Return the deduped items with provenance (which query brought
     each in, and whether via /findSimilar).

For a typical 8-query plan with half marked expand_with_similar=True:
  cost = 8 × 5 + 4 × 5 = 60 credits per cycle.
For 12 queries = 80-100 credits per cycle.

Cadence-gated downstream — daily queries fire on daily clocks, monthly
on monthly clocks. So a typical month's burn for a single user with
12 queries (mix of cadences) is in the 200-500 credit range.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.web.client import exa_find_similar, exa_search, have_exa_key
from backend.web.proactive.cost_gate import exa_automation_paused
from backend.web.proactive.system_b.query_gen import GeneratedQuery
from db.models import ProactiveSignal
from db.session import async_session

logger = logging.getLogger(__name__)


_PER_QUERY_NUM_RESULTS = 3
_PER_SIMILAR_NUM_RESULTS = 3
_QUERY_CONCURRENCY = 4  # cap concurrent /search calls so we don't trip rate limits


@dataclass(frozen=True)
class FetchedItem:
    """One enriched search hit with provenance."""

    url: str
    title: str
    snippet: str
    published_date: str | None
    source_query: str
    angle: str
    via_similar: bool  # True if found through /findSimilar expansion

    def to_signal_payload(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "highlights": [self.snippet] if self.snippet else [],
            "publishedDate": self.published_date,
            "system_b_source_query": self.source_query,
            "system_b_angle": self.angle,
            "system_b_via_similar": self.via_similar,
        }


@dataclass(frozen=True)
class FetchSummary:
    """One batch fetch: aggregated stats."""

    queries_run: int
    search_calls: int
    similar_calls: int
    raw_items: int
    deduped_items: int


def _normalize_item(
    item: dict[str, Any],
    *,
    source_query: str,
    angle: str,
    via_similar: bool,
) -> FetchedItem | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    highlights = item.get("highlights") or []
    snippet = ""
    if isinstance(highlights, list) and highlights:
        snippet = " | ".join(str(h).strip() for h in highlights[:2])
    elif item.get("text"):
        snippet = str(item.get("text"))[:300]
    return FetchedItem(
        url=url,
        title=str(item.get("title") or url)[:300],
        snippet=snippet[:500],
        published_date=item.get("publishedDate"),
        source_query=source_query,
        angle=angle,
        via_similar=via_similar,
    )


async def _existing_user_urls(user_id: str) -> set[str]:
    """All URLs already enqueued for this user, for cross-cycle dedup."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProactiveSignal.payload).where(
                    ProactiveSignal.user_id == user_id,
                )
            )
        ).all()
    out: set[str] = set()
    for r in rows:
        payload = r[0] or {}
        if not isinstance(payload, dict):
            continue
        url = payload.get("url")
        if isinstance(url, str) and url.strip():
            out.add(url.strip())
    return out


async def _fetch_one_query(
    query: GeneratedQuery,
    *,
    semaphore: asyncio.Semaphore,
) -> tuple[list[FetchedItem], int, int]:
    """Run /search (+ optional /findSimilar) for a single query.

    Returns (items, search_calls_made, similar_calls_made). Errors are
    logged and turn into empty results — never raised.
    """
    items: list[FetchedItem] = []
    search_calls = 0
    similar_calls = 0

    async with semaphore:
        try:
            res = await exa_search(
                query.text,
                num_results=_PER_QUERY_NUM_RESULTS,
                search_type="auto",
            )
            search_calls = 1
        except Exception:
            logger.exception(
                "system_b: /search failed for query=%r", query.text[:80]
            )
            return [], 0, 0

    raw = res.get("results") if isinstance(res, dict) else None
    if not isinstance(raw, list):
        raw = []

    for item in raw:
        norm = _normalize_item(
            item,
            source_query=query.text,
            angle=query.angle,
            via_similar=False,
        )
        if norm is not None:
            items.append(norm)

    if query.expand_with_similar and items:
        # Use the top hit's URL as the seed for /findSimilar.
        seed = items[0].url
        async with semaphore:
            try:
                sim_res = await exa_find_similar(
                    seed,
                    num_results=_PER_SIMILAR_NUM_RESULTS,
                    exclude_source_domain=True,
                )
                similar_calls = 1
            except Exception:
                logger.exception(
                    "system_b: /findSimilar failed for seed=%s", seed[:80]
                )
                sim_res = {}
        sim_raw = sim_res.get("results") if isinstance(sim_res, dict) else None
        if isinstance(sim_raw, list):
            for item in sim_raw:
                norm = _normalize_item(
                    item,
                    source_query=query.text,
                    angle=query.angle,
                    via_similar=True,
                )
                if norm is not None:
                    items.append(norm)

    return items, search_calls, similar_calls


async def fetch_for_queries(
    queries: list[GeneratedQuery],
    *,
    user_id: str,
    skip_dedup: bool = False,
) -> tuple[list[FetchedItem], FetchSummary]:
    """Run all queries in parallel (capped), aggregate + dedupe.

    Dedup happens in two passes:
      1. Within-batch: same URL appearing under multiple queries collapses
         to the FIRST query that surfaced it.
      2. Cross-cycle: URLs already in proactive_signals for this user
         are dropped.

    Pass ``skip_dedup=True`` for one-off testing where you want to see
    everything Exa returns.

    Always returns. No-ops gracefully when EXA_API_KEY missing or the
    cost gate is set.
    """
    if not queries:
        return [], FetchSummary(0, 0, 0, 0, 0)
    if exa_automation_paused() or not have_exa_key():
        return [], FetchSummary(0, 0, 0, 0, 0)

    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY)

    results = await asyncio.gather(
        *(_fetch_one_query(q, semaphore=semaphore) for q in queries),
        return_exceptions=False,
    )

    raw_items: list[FetchedItem] = []
    total_search = 0
    total_similar = 0
    for items, sc, simc in results:
        raw_items.extend(items)
        total_search += sc
        total_similar += simc

    # Dedup pass 1: within batch by URL.
    seen_in_batch: set[str] = set()
    batch_unique: list[FetchedItem] = []
    for it in raw_items:
        if it.url in seen_in_batch:
            continue
        seen_in_batch.add(it.url)
        batch_unique.append(it)

    if skip_dedup:
        return batch_unique, FetchSummary(
            queries_run=len(queries),
            search_calls=total_search,
            similar_calls=total_similar,
            raw_items=len(raw_items),
            deduped_items=len(batch_unique),
        )

    # Dedup pass 2: against historical proactive_signals.
    historical = await _existing_user_urls(user_id)
    deduped = [it for it in batch_unique if it.url not in historical]

    return deduped, FetchSummary(
        queries_run=len(queries),
        search_calls=total_search,
        similar_calls=total_similar,
        raw_items=len(raw_items),
        deduped_items=len(deduped),
    )
