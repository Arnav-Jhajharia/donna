"""attention_boost tests — boost rerank_score for hits matching active subjects."""
from __future__ import annotations

from types import SimpleNamespace

from backend.memory.retrieval.attention_boost import apply_attention_boost
from backend.memory.retrieval.types import RetrievalResult


def _hit(id_: str, content: str, rerank: float = 1.0) -> RetrievalResult:
    return RetrievalResult(
        id=id_,
        source="supermemory",
        content=content,
        score=rerank,
        rerank_score=rerank,
        retrieved_via="q",
        metadata={},
    )


def _attention(subject_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        spec=SimpleNamespace(subject=SimpleNamespace(name=subject_name))
    )


def test_boost_applied_case_insensitive() -> None:
    hits = [_hit("a", "talked to Sarah today", 1.0), _hit("b", "grocery list", 1.2)]
    out = apply_attention_boost(hits, [_attention("sarah")])
    assert out[0].id == "a"
    assert out[0].rerank_score > 1.0


def test_no_boost_no_change() -> None:
    hits = [_hit("a", "grocery list", 1.5), _hit("b", "laundry", 1.0)]
    out = apply_attention_boost(hits, [_attention("sarah")])
    assert [h.id for h in out] == ["a", "b"]
    assert out[0].rerank_score == 1.5


def test_empty_attentions_returns_copy() -> None:
    hits = [_hit("a", "x", 1.0)]
    out = apply_attention_boost(hits, [])
    assert out[0].id == "a"
    assert out is not hits


def test_boost_cap_limits_how_many_promoted() -> None:
    hits = [_hit(f"h{i}", "sarah mentions " + str(i), 1.0 - i * 0.01) for i in range(5)]
    out = apply_attention_boost(hits, [_attention("sarah")])
    boosted = [h for h in out if h.rerank_score > 1.0]
    assert len(boosted) <= 3


def test_boost_reorders_when_it_overtakes_base() -> None:
    hits = [_hit("a", "grocery list", 1.0), _hit("b", "sarah called", 0.9)]
    out = apply_attention_boost(hits, [_attention("sarah")])
    # 0.9 * 1.35 = 1.215 > 1.0 → b should be first.
    assert out[0].id == "b"


def test_metadata_title_match() -> None:
    hit = RetrievalResult(
        id="a", source="graphiti", content="",
        score=1.0, rerank_score=1.0, retrieved_via="q",
        metadata={"title": "Antler pitch notes"},
    )
    out = apply_attention_boost([hit], [_attention("antler")])
    assert out[0].rerank_score > 1.0
