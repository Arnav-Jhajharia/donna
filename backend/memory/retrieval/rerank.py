"""Reciprocal Rank Fusion merge+rerank. Ported verbatim."""
from __future__ import annotations

import logging
from collections import defaultdict

from backend.memory.retrieval.types import RetrievalResult

logger = logging.getLogger(__name__)
_RRF_K = 60


def merge_and_rerank(hits: list[RetrievalResult], top_k: int = 12) -> list[RetrievalResult]:
    if not hits:
        return []
    by_group: dict[tuple[str, str], list[RetrievalResult]] = defaultdict(list)
    for h in hits:
        by_group[(h.retrieved_via, h.source)].append(h)
    for group in by_group.values():
        group.sort(key=lambda r: r.score, reverse=True)

    rrf: dict[str, float] = defaultdict(float)
    best: dict[str, RetrievalResult] = {}
    for group in by_group.values():
        for rank, hit in enumerate(group):
            rrf[hit.id] += 1.0 / (_RRF_K + rank) + float(
                hit.metadata.get("structured_priority") or 0.0
            )
            prev = best.get(hit.id)
            if prev is None or hit.score > prev.score:
                best[hit.id] = hit

    merged: list[RetrievalResult] = []
    for hit_id, s in sorted(rrf.items(), key=lambda kv: kv[1], reverse=True):
        rep = best[hit_id]
        merged.append(
            RetrievalResult(
                id=rep.id,
                source=rep.source,
                content=rep.content,
                score=rep.score,
                rerank_score=s,
                retrieved_via=rep.retrieved_via,
                metadata=rep.metadata,
            )
        )
    return merged[:top_k]


async def rerank_with_ce(query: str, hits: list[RetrievalResult], top_k: int = 12):
    return hits[:top_k]
