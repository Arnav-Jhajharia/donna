"""Merge-and-rerank stage for web hits.

Two layers, both optional:

1. ``dedup_by_url`` — collapse duplicate URLs to one representative
   (best provider score wins).
2. ``rrf_merge`` — Reciprocal Rank Fusion across retrieval queries.
   Same algorithm as ``backend.memory.retrieval.rerank.merge_and_rerank``,
   applied to URLs.
3. ``cohere_rerank`` — optional Cohere Rerank v2 cross-encoder pass.
   Degrades to input order when ``COHERE_API_KEY`` is unset or the call
   fails; never raises.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

import httpx

from backend.web.types import WebHit

logger = logging.getLogger(__name__)

_RRF_K = 60
_COHERE_MODEL = "rerank-v3.5"
_COHERE_ENDPOINT = "https://api.cohere.com/v2/rerank"
_COHERE_TIMEOUT_S = 8.0


def have_cohere_key() -> bool:
    return bool(os.environ.get("COHERE_API_KEY", "").strip())


def _url_key(hit: WebHit) -> str:
    """Cheap canonicalization so trailing slashes and case don't fragment."""
    return hit.url.rstrip("/").lower()


def dedup_by_url(hits: list[WebHit]) -> list[WebHit]:
    """Keep the best-scoring representative per URL key."""
    best: dict[str, WebHit] = {}
    for h in hits:
        k = _url_key(h)
        prev = best.get(k)
        if prev is None or h.score > prev.score:
            best[k] = h
    return list(best.values())


def rrf_merge(hits: list[WebHit], *, top_k: int = 12) -> list[WebHit]:
    """Reciprocal Rank Fusion across retrieval queries.

    Each ``retrieved_via`` label becomes one ranked list; each hit gets
    1/(rank + k) credit from every list it appears in. Robust to raw
    score scale differences between lanes (neural vs keyword).
    """
    if not hits:
        return []
    groups: dict[str, list[WebHit]] = defaultdict(list)
    for h in hits:
        groups[h.retrieved_via].append(h)
    for g in groups.values():
        g.sort(key=lambda h: h.score, reverse=True)

    rrf: dict[str, float] = defaultdict(float)
    best: dict[str, WebHit] = {}
    for group in groups.values():
        for rank, hit in enumerate(group):
            k = _url_key(hit)
            rrf[k] += 1.0 / (_RRF_K + rank)
            prev = best.get(k)
            if prev is None or hit.score > prev.score:
                best[k] = hit

    out: list[WebHit] = []
    for k, s in sorted(rrf.items(), key=lambda kv: kv[1], reverse=True):
        rep = best[k]
        out.append(
            WebHit(
                url=rep.url,
                title=rep.title,
                snippet=rep.snippet,
                published_date=rep.published_date,
                author=rep.author,
                score=rep.score,
                rerank_score=s,
                retrieved_via=rep.retrieved_via,
                metadata=rep.metadata,
            )
        )
    return out[:top_k]


async def cohere_rerank(
    query: str,
    hits: list[WebHit],
    *,
    top_k: int = 8,
    model: str = _COHERE_MODEL,
) -> list[WebHit]:
    """Re-order ``hits`` with Cohere Rerank v2. Returns input order on failure."""
    api_key = os.environ.get("COHERE_API_KEY", "").strip()
    if not api_key or not hits:
        return hits[:top_k]

    documents = [f"{h.title}\n{h.snippet}" for h in hits]
    body = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": min(top_k, len(documents)),
    }
    try:
        async with httpx.AsyncClient(timeout=_COHERE_TIMEOUT_S) as client:
            resp = await client.post(
                _COHERE_ENDPOINT,
                json=body,
                headers={
                    "authorization": f"Bearer {api_key}",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("cohere_rerank failed: %s", exc)
        return hits[:top_k]

    reordered: list[WebHit] = []
    for item in (data.get("results") or []):
        idx = item.get("index")
        score = float(item.get("relevance_score") or 0.0)
        if not isinstance(idx, int) or idx < 0 or idx >= len(hits):
            continue
        src = hits[idx]
        reordered.append(
            WebHit(
                url=src.url,
                title=src.title,
                snippet=src.snippet,
                published_date=src.published_date,
                author=src.author,
                score=src.score,
                rerank_score=score,
                retrieved_via=src.retrieved_via,
                metadata={**src.metadata, "cohere_relevance": score},
            )
        )
    return reordered[:top_k] if reordered else hits[:top_k]
