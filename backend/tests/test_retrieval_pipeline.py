"""Rerank (RRF) unit tests — no external deps."""
from __future__ import annotations

from backend.memory.retrieval.rerank import merge_and_rerank
from backend.memory.retrieval.types import RetrievalResult


def _hit(id_: str, source: str, score: float, query: str, content: str = "c") -> RetrievalResult:
    return RetrievalResult(
        id=id_, source=source, content=content, score=score, retrieved_via=query
    )


def test_rerank_empty():
    assert merge_and_rerank([]) == []


def test_rerank_dedupes_by_id():
    hits = [
        _hit("sm:a", "supermemory", 0.9, "q1"),
        _hit("sm:a", "supermemory", 0.5, "q2"),
        _hit("sm:b", "supermemory", 0.8, "q1"),
    ]
    out = merge_and_rerank(hits, top_k=10)
    ids = [h.id for h in out]
    assert ids.count("sm:a") == 1


def test_rerank_rrf_order():
    hits = [
        _hit("sm:a", "supermemory", 0.9, "q1"),
        _hit("sm:a", "supermemory", 0.9, "q2"),  # same doc from 2 queries
        _hit("sm:b", "supermemory", 0.95, "q1"),  # higher score but only 1 query
    ]
    out = merge_and_rerank(hits, top_k=10)
    assert out[0].id == "sm:a"


def test_rerank_top_k():
    hits = [_hit(f"sm:{i}", "supermemory", 0.5, "q") for i in range(20)]
    out = merge_and_rerank(hits, top_k=5)
    assert len(out) == 5


def test_rerank_preserves_best_metadata():
    hits = [
        _hit("sm:a", "supermemory", 0.5, "q1", content="low"),
        _hit("sm:a", "supermemory", 0.9, "q2", content="high"),
    ]
    out = merge_and_rerank(hits, top_k=1)
    assert out[0].content == "high"


def test_rerank_respects_structured_priority():
    semantic = _hit("gt:a", "graphiti", 1.0, "q1")
    structured = RetrievalResult(
        id="obs:summary:a",
        source="observations",
        content="expense total 6 usd",
        score=1.0,
        retrieved_via="q1",
        metadata={"structured_priority": 0.08},
    )

    out = merge_and_rerank([semantic, structured], top_k=2)

    assert out[0].id == "obs:summary:a"
