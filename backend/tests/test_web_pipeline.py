"""End-to-end tests for the web research pipeline.

All network + LLM seams are mocked: ``backend.web.client.exa_search`` +
``exa_find_similar`` for fanout, ``call_structured`` for expansion and
synthesis, ``cohere_rerank`` for the optional rerank layer.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.web import expansion as web_expansion
from backend.web import fanout as web_fanout
from backend.web import pipeline as web_pipeline
from backend.web import rerank as web_rerank
from backend.web import synthesis as web_synthesis
from backend.web.types import WebExpansion, WebHit


# ---------------------------------------------------------------------------
# rerank: pure-logic tests (no mocks)
# ---------------------------------------------------------------------------


def _hit(url: str, via: str, score: float = 0.5) -> WebHit:
    return WebHit(url=url, title=url, snippet="", score=score, retrieved_via=via)


def test_dedup_by_url_keeps_best_score():
    hits = [
        _hit("https://a.test", "neural:q1", score=0.3),
        _hit("https://a.test/", "keyword:q2", score=0.9),  # trailing slash = same canonical
        _hit("https://b.test", "neural:q1", score=0.5),
    ]
    out = web_rerank.dedup_by_url(hits)
    assert len(out) == 2
    a = [h for h in out if "a.test" in h.url][0]
    assert a.score == 0.9


def test_rrf_merge_rewards_multi_list_appearance():
    # a appears in two lists; b only in one. a should outrank b even if b's
    # raw score is higher, because RRF uses rank not raw score.
    hits = [
        _hit("https://a.test", "neural:q1", score=0.1),
        _hit("https://b.test", "neural:q1", score=0.9),
        _hit("https://a.test", "keyword:q2", score=0.1),
    ]
    out = web_rerank.rrf_merge(hits, top_k=5)
    assert len(out) == 2
    assert "a.test" in out[0].url
    assert out[0].rerank_score > out[1].rerank_score


def test_rrf_merge_empty_returns_empty():
    assert web_rerank.rrf_merge([], top_k=5) == []


@pytest.mark.asyncio
async def test_cohere_rerank_falls_back_when_no_key(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    hits = [_hit("https://a.test", "neural:q", 0.5), _hit("https://b.test", "neural:q", 0.4)]
    out = await web_rerank.cohere_rerank("q", hits, top_k=10)
    # unchanged order when no key
    assert [h.url for h in out] == ["https://a.test", "https://b.test"]


# ---------------------------------------------------------------------------
# expansion: Haiku fallback + happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expansion_fallback_when_call_structured_returns_none(monkeypatch):
    async def fake(**kwargs):
        return None

    monkeypatch.setattr(web_expansion, "call_structured", fake)
    exp = await web_expansion.expand_research_query("compare poke and limitless")
    assert exp.neural_queries == ["compare poke and limitless"]
    assert exp.keyword_queries == []
    assert exp.hypothetical is None


@pytest.mark.asyncio
async def test_expansion_uses_structured_output(monkeypatch):
    class _Out:
        rewritten_query = "compare poke vs limitless ai hardware 2026"
        neural_queries = [
            "articles comparing poke and limitless ai hardware design",
            "poke vs limitless reviews 2026",
            "",  # blank gets dropped
        ]
        keyword_queries = ["poke limitless comparison"]
        hypothetical = "Poke emphasizes an always-on mic while Limitless ships a necklace form factor."

    async def fake(**kwargs):
        return _Out()

    monkeypatch.setattr(web_expansion, "call_structured", fake)
    exp = await web_expansion.expand_research_query("compare poke and limitless")
    assert exp.rewritten_query.startswith("compare poke")
    assert len(exp.neural_queries) == 2  # blank dropped
    assert exp.keyword_queries == ["poke limitless comparison"]
    assert exp.hypothetical is not None


@pytest.mark.asyncio
async def test_expansion_empty_question_returns_empty_plan(monkeypatch):
    exp = await web_expansion.expand_research_query("   ")
    assert exp.rewritten_query == ""
    assert exp.neural_queries == []


# ---------------------------------------------------------------------------
# fanout: parallel Exa with mocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_runs_all_lanes(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_search(query, *, num_results, search_type, with_contents):
        calls.append((search_type, query))
        return {
            "results": [
                {
                    "id": f"id-{query[:5]}",
                    "url": f"https://{search_type}-{len(calls)}.test",
                    "title": f"{search_type} {query[:10]}",
                    "score": 0.8,
                    "highlights": [f"highlight for {query[:10]}"],
                    "text": "body",
                }
            ]
        }

    async def fake_similar(url, *, num_results, with_contents):
        return {
            "results": [
                {
                    "id": "similar-1",
                    "url": "https://similar.test",
                    "title": "similar page",
                    "score": 0.7,
                    "highlights": ["similar highlight"],
                }
            ]
        }

    monkeypatch.setattr(web_fanout, "exa_search", fake_search)
    monkeypatch.setattr(web_fanout, "exa_find_similar", fake_similar)

    expansion = WebExpansion(
        rewritten_query="q",
        neural_queries=["neural one", "neural two"],
        keyword_queries=["keyword one"],
        hypothetical="hypothetical sentence",
    )
    hits = await web_fanout.fanout(expansion=expansion, seed_url="https://seed.test")

    # 2 neural + 1 hypothetical neural + 1 auto (was keyword) + 1 find_similar
    assert len(calls) == 4  # find_similar is separate
    search_types = [c[0] for c in calls]
    assert search_types.count("neural") == 3
    # Exa deprecated `keyword`; we route the keyword lane through `auto`.
    assert search_types.count("auto") == 1
    assert len(hits) == 5  # one hit per lane
    assert any("similar" in h.url for h in hits)


@pytest.mark.asyncio
async def test_fanout_one_lane_failing_does_not_take_down_pool(monkeypatch):
    call_count = {"n": 0}

    async def fake_search(query, *, num_results, search_type, with_contents):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("lane failure")
        return {
            "results": [
                {
                    "id": "ok",
                    "url": "https://ok.test",
                    "title": "ok",
                    "score": 0.5,
                    "highlights": ["ok"],
                }
            ]
        }

    monkeypatch.setattr(web_fanout, "exa_search", fake_search)
    expansion = WebExpansion(
        rewritten_query="q",
        neural_queries=["q1", "q2"],
        keyword_queries=[],
        hypothetical=None,
    )
    hits = await web_fanout.fanout(expansion=expansion)
    assert len(hits) == 1
    assert hits[0].url == "https://ok.test"


# ---------------------------------------------------------------------------
# synthesis: two-prompt + judge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_empty_hits_returns_empty_answer():
    ans = await web_synthesis.synthesize_with_compare("question", [])
    assert ans.answer == ""
    assert ans.confidence == 0.0


@pytest.mark.asyncio
async def test_synthesis_calls_three_models_and_picks_judge_choice(monkeypatch):
    call_log: list[str] = []

    async def fake(**kwargs):
        system = kwargs["system_prompt"]
        if "research judge" in system.lower():
            call_log.append("judge")

            class Out:
                choice = "merged"
                answer = "Final merged answer."
                confidence = 0.78
                dissent = "broad noted a specific caveat."

            return Out()
        if "strictly from the supplied sources" in system.lower():
            call_log.append("strict")

            class Out:
                answer = "Strict answer only from sources."

            return Out()
        call_log.append("broad")

        class Out:
            answer = "Broad answer with weak signals noted."

        return Out()

    monkeypatch.setattr(web_synthesis, "call_structured", fake)

    hits = [
        WebHit(url="https://a.test", title="A", snippet="a body", score=0.9, retrieved_via="neural:q"),
        WebHit(url="https://b.test", title="B", snippet="b body", score=0.8, retrieved_via="keyword:q"),
    ]
    ans = await web_synthesis.synthesize_with_compare("what's the story", hits)
    assert call_log.count("strict") == 1
    assert call_log.count("broad") == 1
    assert call_log.count("judge") == 1
    assert ans.answer == "Final merged answer."
    assert ans.confidence == pytest.approx(0.78)
    assert ans.dissent == "broad noted a specific caveat."
    assert ans.metadata["variant"] == "merged"
    assert len(ans.sources) == 2


@pytest.mark.asyncio
async def test_synthesis_judge_failure_falls_back_to_strict(monkeypatch):
    async def fake(**kwargs):
        system = kwargs["system_prompt"]
        if "research judge" in system.lower():
            return None  # judge failed
        if "strictly from the supplied sources" in system.lower():
            class Out:
                answer = "Strict text."
            return Out()
        class Out2:
            answer = "Broad text."
        return Out2()

    monkeypatch.setattr(web_synthesis, "call_structured", fake)
    hits = [WebHit(url="https://a.test", title="A", snippet="s", score=0.5, retrieved_via="n:q")]
    ans = await web_synthesis.synthesize_with_compare("q", hits)
    assert ans.answer == "Strict text."
    assert ans.dissent == "Broad text."
    assert ans.metadata["variant"] == "strict_fallback"


# ---------------------------------------------------------------------------
# pipeline: orchestrator — end-to-end with mocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_degrades_without_exa_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    answer, trace = await web_pipeline.run_web_research("anything")
    assert answer.answer == ""
    assert answer.metadata["reason"] == "EXA_API_KEY not set"
    assert trace.reranker_used == "none"
    assert trace.merged_count == 0


@pytest.mark.asyncio
async def test_pipeline_empty_question_is_empty(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    answer, trace = await web_pipeline.run_web_research("   ")
    assert answer.answer == ""
    assert trace.merged_count == 0


@pytest.mark.asyncio
async def test_pipeline_full_flow_with_all_seams_mocked(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    monkeypatch.delenv("COHERE_API_KEY", raising=False)  # rrf_only path

    async def fake_expansion(question, *, profile_blurb=""):
        return WebExpansion(
            rewritten_query=question,
            neural_queries=["neural variant"],
            keyword_queries=["keyword variant"],
            hypothetical="hypothetical shaped like answer",
        )

    async def fake_fanout(*, expansion, per_query_limit, seed_url):
        return [
            WebHit(url="https://a.test", title="A", snippet="s1", score=0.9, retrieved_via="neural:variant"),
            WebHit(url="https://b.test", title="B", snippet="s2", score=0.8, retrieved_via="keyword:variant"),
            WebHit(url="https://a.test/", title="A dup", snippet="s3", score=0.7, retrieved_via="neural:other"),
        ]

    async def fake_synth(question, hits, *, sources_limit=8):
        from backend.web.types import WebAnswer
        return WebAnswer(
            answer="Final answer from pipeline.",
            confidence=0.82,
            sources=list(hits),
            dissent=None,
            metadata={"variant": "merged"},
        )

    monkeypatch.setattr(web_pipeline, "expand_research_query", fake_expansion)
    monkeypatch.setattr(web_pipeline, "fanout", fake_fanout)
    monkeypatch.setattr(web_pipeline, "synthesize_with_compare", fake_synth)

    answer, trace = await web_pipeline.run_web_research("test question", top_k=5)
    assert answer.answer == "Final answer from pipeline."
    assert answer.confidence == pytest.approx(0.82)
    assert trace.reranker_used == "rrf_only"
    assert trace.merged_count == 2  # a.test dedup + b.test
    assert trace.reranked_count <= 5
    assert "expansion_ms" in trace.timings_ms
    assert "fanout_ms" in trace.timings_ms
    assert "synthesis_ms" in trace.timings_ms


@pytest.mark.asyncio
async def test_pipeline_uses_cohere_when_key_present(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa_test")
    monkeypatch.setenv("COHERE_API_KEY", "co_test")

    async def fake_expansion(question, *, profile_blurb=""):
        return WebExpansion(rewritten_query=question, neural_queries=["q"], keyword_queries=[], hypothetical=None)

    async def fake_fanout(*, expansion, per_query_limit, seed_url):
        return [WebHit(url="https://a.test", title="A", snippet="s", score=0.5, retrieved_via="neural:q")]

    async def fake_cohere(query, hits, *, top_k=8, model="rerank-v3.5"):
        return hits[:top_k]

    async def fake_synth(question, hits, *, sources_limit=8):
        from backend.web.types import WebAnswer
        return WebAnswer(answer="ok", confidence=0.5, sources=list(hits))

    monkeypatch.setattr(web_pipeline, "expand_research_query", fake_expansion)
    monkeypatch.setattr(web_pipeline, "fanout", fake_fanout)
    monkeypatch.setattr(web_pipeline, "cohere_rerank", fake_cohere)
    monkeypatch.setattr(web_pipeline, "synthesize_with_compare", fake_synth)

    _, trace = await web_pipeline.run_web_research("q")
    assert trace.reranker_used == "cohere"
