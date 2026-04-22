"""Parallel fanout to Supermemory + Graphiti. Ported from backend-v2."""
from __future__ import annotations

import asyncio
import hashlib
import logging

from backend.memory.clients.graphiti import search_facts as graphiti_search
from backend.memory.clients.supermemory import get_memory_client
from backend.memory.retrieval.types import RetrievalResult

logger = logging.getLogger(__name__)

_PER_QUERY_LIMIT = 6
_LANE_TIMEOUT = 8.0


async def fanout(
    *,
    user_id: str,
    queries: list[str],
    per_query_limit: int = _PER_QUERY_LIMIT,
    use_supermemory: bool = True,
    use_graphiti: bool = True,
) -> list[RetrievalResult]:
    tasks: list[asyncio.Task] = []
    for q in queries:
        if not q.strip():
            continue
        if use_supermemory:
            tasks.append(asyncio.create_task(_search_sm(user_id, q, per_query_limit)))
        if use_graphiti:
            tasks.append(asyncio.create_task(_search_gt(user_id, q, per_query_limit)))
    if not tasks:
        return []
    batched = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[RetrievalResult] = []
    for b in batched:
        if isinstance(b, Exception):
            logger.warning("fanout lane failed: %s", b)
            continue
        results.extend(b)
    return results


async def _search_sm(user_id: str, query: str, limit: int) -> list[RetrievalResult]:
    try:
        hits = await asyncio.wait_for(
            get_memory_client().search_with_graph(user_id, query, limit=limit),
            timeout=_LANE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.sm failed")
        return []
    return [
        RetrievalResult(
            id=f"sm:{h.id}",
            source="supermemory",
            content=h.content,
            score=h.score,
            retrieved_via=query,
            metadata={"updated_at": h.updated_at, "relations": h.relations, **h.metadata},
        )
        for h in hits
        if h.id
    ]


async def _search_gt(user_id: str, query: str, limit: int) -> list[RetrievalResult]:
    try:
        facts = await asyncio.wait_for(
            graphiti_search(user_id, query, limit=limit), timeout=_LANE_TIMEOUT
        )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.gt failed")
        return []
    return [
        RetrievalResult(
            id=f"gt:{f.get('uuid') or _hash(f.get('fact', ''))}",
            source="graphiti",
            content=f.get("fact", ""),
            score=1.0,
            retrieved_via=query,
            metadata={
                "valid_at": f.get("valid_at"),
                "invalid_at": f.get("invalid_at"),
                "created_at": f.get("created_at"),
                "episodes": f.get("episodes") or [],
            },
        )
        for f in facts
        if f.get("fact")
    ]


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]
