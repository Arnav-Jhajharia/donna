"""Orchestrator: expand -> fanout -> merge+rerank."""
from __future__ import annotations

import logging
import time

from backend.memory.retrieval.attention_boost import apply_attention_boost
from backend.memory.retrieval.expansion import Intent, expand_query
from backend.memory.retrieval.fanout import fanout
from backend.memory.retrieval.rerank import merge_and_rerank
from backend.memory.retrieval.types import Expansion, RetrievalResult, RetrievalTrace

logger = logging.getLogger(__name__)


async def run_retrieval(
    *,
    user_id: str,
    message: str,
    profile_blurb: str = "",
    recent_thread: str = "",
    current_datetime: str = "",
    intent_hint: Intent = "unknown",
    top_k: int = 12,
    per_query_limit: int = 6,
    use_supermemory: bool = True,
    use_graphiti: bool = True,
    active_attentions: list[object] | None = None,
) -> tuple[list[RetrievalResult], RetrievalTrace]:
    timings: dict[str, int] = {}
    t0 = time.perf_counter()
    exp_out = await expand_query(
        message=message,
        profile_blurb=profile_blurb,
        recent_thread=recent_thread,
        current_datetime=current_datetime,
        intent_hint=intent_hint,
    )
    timings["expansion_ms"] = round((time.perf_counter() - t0) * 1000)

    if exp_out is None:
        expansion = Expansion(rewritten_query=message, facets=[], hypothetical=None)
    else:
        expansion = Expansion(
            rewritten_query=exp_out.rewritten_query or message,
            facets=list(exp_out.facets or []),
            hypothetical=exp_out.hypothetical,
        )
    queries = _build_query_list(expansion)

    t0 = time.perf_counter()
    raw = await fanout(
        user_id=user_id,
        queries=queries,
        original_message=message,
        per_query_limit=per_query_limit,
        use_supermemory=use_supermemory,
        use_graphiti=use_graphiti,
    )
    timings["fanout_ms"] = round((time.perf_counter() - t0) * 1000)

    hits_by_query: dict[str, int] = {}
    hits_by_source: dict[str, int] = {}
    for h in raw:
        hits_by_query[h.retrieved_via] = hits_by_query.get(h.retrieved_via, 0) + 1
        hits_by_source[h.source] = hits_by_source.get(h.source, 0) + 1

    t0 = time.perf_counter()
    final = merge_and_rerank(raw, top_k=top_k)
    if active_attentions:
        final = apply_attention_boost(final, active_attentions)
    timings["rerank_ms"] = round((time.perf_counter() - t0) * 1000)

    trace = RetrievalTrace(
        expansion=expansion,
        queries_fired=queries,
        raw_hits_by_query=hits_by_query,
        raw_hits_by_source=hits_by_source,
        merged_count=len({h.id for h in raw}),
        reranked_count=len(final),
        timings_ms=timings,
    )
    return final, trace


def _build_query_list(expansion: Expansion) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in [expansion.rewritten_query, *expansion.facets]:
        k = (q or "").strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    if expansion.hypothetical:
        h = expansion.hypothetical.strip()
        if h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return out
