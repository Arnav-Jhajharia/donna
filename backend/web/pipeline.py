"""Web research pipeline orchestrator.

Shape mirrors ``backend.memory.retrieval.pipeline.run_retrieval``:

    expand → fanout → dedup → RRF → (optional) Cohere rerank → synthesize

with the two extras that make this more than cleaner RAG:

- URL dedup between fanout and RRF.
- Two-prompt synthesis (strict vs broad) + judge at the end.

Contract:
- Never raises. Degrades at every node. Returns a ``WebAnswer`` (possibly
  empty) and a ``WebTrace`` recording what ran.
"""
from __future__ import annotations

import logging
import time

from backend.web.client import have_exa_key
from backend.web.expansion import expand_research_query
from backend.web.fanout import fanout
from backend.web.rerank import cohere_rerank, dedup_by_url, have_cohere_key, rrf_merge
from backend.web.synthesis import synthesize_with_compare
from backend.web.types import WebAnswer, WebExpansion, WebTrace

logger = logging.getLogger(__name__)


def _empty_expansion(question: str) -> WebExpansion:
    return WebExpansion(
        rewritten_query=question,
        neural_queries=[],
        keyword_queries=[],
        hypothetical=None,
    )


async def run_web_research(
    question: str,
    *,
    top_k: int = 8,
    per_query_limit: int = 6,
    profile_blurb: str = "",
    seed_url: str | None = None,
) -> tuple[WebAnswer, WebTrace]:
    timings: dict[str, int] = {}
    q = (question or "").strip()
    if not q:
        return (
            WebAnswer(answer="", confidence=0.0, sources=[]),
            WebTrace(
                expansion=_empty_expansion(""),
                queries_fired=[],
                hits_by_query={},
                merged_count=0,
                reranked_count=0,
                timings_ms=timings,
                reranker_used="none",
            ),
        )

    if not have_exa_key():
        return (
            WebAnswer(
                answer="",
                confidence=0.0,
                sources=[],
                metadata={"reason": "EXA_API_KEY not set"},
            ),
            WebTrace(
                expansion=_empty_expansion(q),
                queries_fired=[],
                hits_by_query={},
                merged_count=0,
                reranked_count=0,
                timings_ms=timings,
                reranker_used="none",
            ),
        )

    # 1. Expansion (Haiku)
    t0 = time.perf_counter()
    expansion = await expand_research_query(q, profile_blurb=profile_blurb)
    timings["expansion_ms"] = round((time.perf_counter() - t0) * 1000)

    # 2. Parallel fanout across Exa lanes
    t0 = time.perf_counter()
    raw = await fanout(
        expansion=expansion,
        per_query_limit=per_query_limit,
        seed_url=seed_url,
    )
    timings["fanout_ms"] = round((time.perf_counter() - t0) * 1000)

    hits_by_query: dict[str, int] = {}
    for h in raw:
        hits_by_query[h.retrieved_via] = hits_by_query.get(h.retrieved_via, 0) + 1

    # 3. URL dedup + RRF merge
    t0 = time.perf_counter()
    deduped = dedup_by_url(raw)
    merged = rrf_merge(raw, top_k=max(top_k * 2, 16))
    timings["rrf_ms"] = round((time.perf_counter() - t0) * 1000)

    # 4. Optional Cohere rerank
    t0 = time.perf_counter()
    if have_cohere_key() and merged:
        reranked = await cohere_rerank(q, merged, top_k=top_k)
        reranker_used = "cohere"
    else:
        reranked = merged[:top_k]
        reranker_used = "rrf_only"
    timings["rerank_ms"] = round((time.perf_counter() - t0) * 1000)

    # 5. Two-prompt synthesis + judge (Haiku x3 max)
    t0 = time.perf_counter()
    answer = await synthesize_with_compare(q, reranked, sources_limit=top_k)
    timings["synthesis_ms"] = round((time.perf_counter() - t0) * 1000)

    trace = WebTrace(
        expansion=expansion,
        queries_fired=list(hits_by_query.keys()),
        hits_by_query=hits_by_query,
        merged_count=len(deduped),
        reranked_count=len(reranked),
        timings_ms=timings,
        reranker_used=reranker_used,
    )
    return answer, trace
