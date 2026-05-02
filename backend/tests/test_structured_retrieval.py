from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.memory.retrieval.structured_hints import detect_structured_hints
from backend.memory.retrieval.types import RetrievalResult


def test_detects_expense_period_from_original_message():
    hints = detect_structured_hints(
        "how much did I spend this week",
        ["weekly expenses"],
    )

    assert hints.wants_observations is True
    assert hints.observation_type == "expense"
    assert hints.period == "this_week"


def test_original_period_wins_over_expansion_period_noise():
    hints = detect_structured_hints(
        "how much did I spend this week",
        ["today's expenses", "coffee spend today"],
    )

    assert hints.period == "this_week"


def test_detects_open_loop_and_situation_questions():
    loops = detect_structured_hints("what am i forgetting")
    brief = detect_structured_hints("what's going on with my week")

    assert loops.wants_open_loops is True
    assert brief.wants_situation_brief is True


def test_open_loop_detector_catches_conversational_phrasings():
    """The detector was missing obvious live phrasings; these should all
    flip wants_open_loops so the open_loops lane fires."""
    phrases = [
        "open loops",
        "what am i tracking",
        "what's on my plate today",
        "what's pulling on me this week",
        "what did i say i'd do",
    ]
    for phrase in phrases:
        hints = detect_structured_hints(phrase)
        assert hints.wants_open_loops is True, (
            f"expected wants_open_loops for {phrase!r}"
        )


def test_habit_shape_flips_wants_observations_with_period():
    h1 = detect_structured_hints("did i drink water today")
    assert h1.wants_observations is True
    assert h1.period == "today"

    h2 = detect_structured_hints("did i sleep enough this week")
    assert h2.wants_observations is True
    assert h2.period == "this_week"

    h3 = detect_structured_hints("drank water this morning")
    assert h3.wants_observations is True


def test_calendar_phrases_flip_wants_calendar():
    assert detect_structured_hints("what's on my calendar today").wants_calendar is True
    assert detect_structured_hints("any meetings tomorrow").wants_calendar is True
    assert detect_structured_hints("lunch with maya").wants_calendar is True
    # Bare temporal queries also flip calendar intent.
    assert detect_structured_hints("what's on today").wants_calendar is True


def test_irrelevant_query_does_not_flip_calendar_or_open_loops():
    hints = detect_structured_hints("explain quantum tunneling")
    assert hints.wants_calendar is False
    assert hints.wants_open_loops is False
    assert hints.wants_observations is False


@pytest.mark.asyncio
async def test_fanout_passes_original_message_to_structured_observation_lane(monkeypatch):
    from backend.memory.retrieval import fanout as fanout_mod

    captured = {}

    async def fake_observations(user_id, query, hints, limit):
        captured["user_id"] = user_id
        captured["query"] = query
        captured["hints"] = hints
        captured["limit"] = limit
        return [
            RetrievalResult(
                id="obs:summary:test",
                source="observations",
                content="expense observations this_week: total 6 USD",
                score=1.2,
                retrieved_via=query,
            )
        ]

    monkeypatch.setattr(fanout_mod, "_search_observations", fake_observations)

    results = await fanout_mod.fanout(
        user_id="user-1",
        queries=["weekly expenses"],
        original_message="how much did I spend this week",
        use_supermemory=False,
        use_graphiti=False,
        use_open_loops=False,
        use_situation_brief=False,
    )

    assert results[0].source == "observations"
    assert captured["query"] == "how much did I spend this week"
    assert captured["hints"].observation_type == "expense"
    assert captured["hints"].period == "this_week"


def test_observation_aggregate_sums_expenses_by_currency():
    from backend.memory.retrieval.fanout import _aggregate_observations

    rows = [
        SimpleNamespace(type="expense", fields={"amount": 6, "currency": "USD"}),
        SimpleNamespace(type="expense", fields={"amount_usd": 12}),
        SimpleNamespace(type="expense", fields={"amount": 9, "currency": "SGD"}),
    ]

    aggregate = _aggregate_observations(rows)

    assert aggregate["totals_by_currency"] == {"USD": 18.0, "SGD": 9.0}


@pytest.mark.asyncio
async def test_fanout_includes_documents_lane(monkeypatch):
    """Without this lane, recall(auto) misses every chunk inside an
    uploaded document — the brain has to know to call recall_document_chunks
    explicitly. Adding documents to the unified fanout closes that gap."""
    from backend.memory.retrieval import fanout as fanout_mod
    from backend.memory.clients.supermemory import ChunkResult

    fake_chunks = [
        ChunkResult(
            content="Ravi is building a fintech for street vendors in Bandra.",
            score=0.92,
            doc_id="doc-abc123",
            metadata={"title": "ravi-meeting-notes.md"},
        ),
        ChunkResult(
            content="He mentioned wanting to talk to investors next month.",
            score=0.88,
            doc_id="doc-abc123",
            metadata={"title": "ravi-meeting-notes.md"},
        ),
    ]

    class _FakeClient:
        async def search_document_chunks(self, user_id, query, doc_id=None, limit=10):
            return fake_chunks

    monkeypatch.setattr(fanout_mod, "get_memory_client", lambda: _FakeClient())

    results = await fanout_mod.fanout(
        user_id="user-1",
        queries=["who was that founder"],
        original_message="who was that founder I told you about",
        use_supermemory=False,
        use_graphiti=False,
        use_observations=False,
        use_open_loops=False,
        use_situation_brief=False,
        use_documents=True,
    )

    assert len(results) == 2
    assert all(r.source == "documents" for r in results)
    assert "Ravi" in results[0].content
    assert results[0].metadata["doc_id"] == "doc-abc123"
    # Stable id format means the same chunk surfacing across multiple
    # query facets dedupes at rerank time.
    assert results[0].id.startswith("doc:doc-abc123:")


@pytest.mark.asyncio
async def test_fanout_respects_use_documents_false(monkeypatch):
    """Caller can disable the documents lane (e.g. when the question
    is clearly conversational, not document-content)."""
    from backend.memory.retrieval import fanout as fanout_mod

    called = {"docs": False}

    async def fake_docs(user_id, query, limit):
        called["docs"] = True
        return []

    monkeypatch.setattr(fanout_mod, "_search_docs", fake_docs)

    await fanout_mod.fanout(
        user_id="user-1",
        queries=["hi"],
        use_supermemory=False,
        use_graphiti=False,
        use_observations=False,
        use_open_loops=False,
        use_situation_brief=False,
        use_documents=False,
        use_calendar=False,
    )

    assert called["docs"] is False


@pytest.mark.asyncio
async def test_docs_lane_downweights_recent_chat_fragments(monkeypatch):
    """USER:/DONNA: chat fragments shouldn't dominate recall — RECENT CHAT
    is already in the wrapped prompt. Real PDF/note bodies keep full weight."""
    from backend.memory.clients.supermemory import ChunkResult
    from backend.memory.retrieval import fanout as fanout_mod

    fake_chunks = [
        ChunkResult(
            content="USER: hi\nDONNA: up already? drink water first thing.",
            score=1.0,
            doc_id="doc-chat",
            metadata={"title": "chat", "created_at": "2026-04-30T10:00:00Z"},
        ),
        ChunkResult(
            content="Ravi is building a fintech for street vendors in Bandra.",
            score=1.0,
            doc_id="doc-pdf",
            metadata={"title": "ravi-meeting-notes.md", "created_at": "2026-04-30T10:00:00Z"},
        ),
    ]

    class _FakeClient:
        async def search_document_chunks(self, user_id, query, doc_id=None, limit=10):
            return fake_chunks

    monkeypatch.setattr(fanout_mod, "get_memory_client", lambda: _FakeClient())

    results = await fanout_mod._search_docs("user-1", "deploy", 10)
    by_doc = {r.metadata.get("doc_id"): r for r in results}
    assert by_doc["doc-chat"].score == pytest.approx(0.5)
    assert by_doc["doc-pdf"].score == pytest.approx(1.0)
    assert by_doc["doc-chat"].metadata.get("chat_fragment_downweight") == 0.5
    assert "chat_fragment_downweight" not in by_doc["doc-pdf"].metadata


@pytest.mark.asyncio
async def test_docs_lane_keeps_old_chat_fragments_at_full_weight(monkeypatch):
    """A chat fragment older than the recency window keeps full weight —
    we only suppress chat that the wrapped prompt's RECENT CHAT could overlap."""
    from backend.memory.clients.supermemory import ChunkResult
    from backend.memory.retrieval import fanout as fanout_mod

    fake_chunks = [
        ChunkResult(
            content="USER: long ago\nDONNA: ancient context",
            score=1.0,
            doc_id="doc-old-chat",
            metadata={"title": "chat", "created_at": "2024-01-01T10:00:00Z"},
        ),
    ]

    class _FakeClient:
        async def search_document_chunks(self, user_id, query, doc_id=None, limit=10):
            return fake_chunks

    monkeypatch.setattr(fanout_mod, "get_memory_client", lambda: _FakeClient())

    results = await fanout_mod._search_docs("user-1", "deploy", 10)
    assert results[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fanout_includes_calendar_lane(monkeypatch):
    """Calendar was explicitly NOT in the fanout per CLAUDE.md; this
    asserts the new lane fires when calendar phrasing is present."""
    from backend.memory.retrieval import fanout as fanout_mod
    from backend.memory.retrieval.types import RetrievalResult

    captured = {}

    async def fake_calendar(user_id, query, hints, limit):
        captured["query"] = query
        captured["hints"] = hints
        return [
            RetrievalResult(
                id="cal:evt-1",
                source="calendar",
                content="calendar: lunch with maya at 2026-05-03 12:30 Asia/Singapore",
                score=1.4,
                retrieved_via=query,
            )
        ]

    monkeypatch.setattr(fanout_mod, "_search_calendar", fake_calendar)

    results = await fanout_mod.fanout(
        user_id="user-1",
        queries=["lunch with maya"],
        original_message="what's on my calendar today",
        use_supermemory=False,
        use_graphiti=False,
        use_observations=False,
        use_open_loops=False,
        use_situation_brief=False,
        use_documents=False,
        use_calendar=True,
    )

    assert any(r.source == "calendar" for r in results)
    assert captured["hints"].wants_calendar is True


@pytest.mark.asyncio
async def test_fanout_respects_use_calendar_false(monkeypatch):
    from backend.memory.retrieval import fanout as fanout_mod

    called = {"cal": False}

    async def fake_calendar(user_id, query, hints, limit):
        called["cal"] = True
        return []

    monkeypatch.setattr(fanout_mod, "_search_calendar", fake_calendar)

    await fanout_mod.fanout(
        user_id="user-1",
        queries=["hi"],
        use_supermemory=False,
        use_graphiti=False,
        use_observations=False,
        use_open_loops=False,
        use_situation_brief=False,
        use_documents=False,
        use_calendar=False,
    )

    assert called["cal"] is False
