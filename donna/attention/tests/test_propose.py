"""Tests for the proactive proposer."""
from __future__ import annotations

import asyncio

import pytest

from donna.attention.propose import (
    CalendarRecurrenceProposer,
    CandidateIntent,
    _normalize_title,
    propose_and_shadow,
    propose_candidates,
)
from donna.attention.schema import AttentionOrigin, AttentionStatus
from donna.attention.store import AttentionStore


class _FakeCalendarFetcher:
    def __init__(self, events):
        self._events = events

    def fetch(self, source, user_id):
        return list(self._events)


@pytest.mark.unit
@pytest.mark.parametrize(
    "a,b",
    [
        ("1:1 with Sarah", "1:1 with Sarah - rescheduled"),
        ("Weekly eng sync", "Weekly eng sync"),
        ("Standup", "standup"),
    ],
)
def test_normalize_title_collapses_recurrences(a, b):
    assert _normalize_title(a) == _normalize_title(b)


@pytest.mark.unit
def test_calendar_proposer_flags_recurring_titles():
    fetcher = _FakeCalendarFetcher(
        [
            {"id": "1", "title": "1:1 with Sarah"},
            {"id": "2", "title": "1:1 with Sarah"},
            {"id": "3", "title": "Flight DL 442"},
        ]
    )
    proposer = CalendarRecurrenceProposer(fetcher=fetcher)
    candidates = proposer.propose("u1")
    assert len(candidates) == 1
    assert "sarah" in candidates[0].raw_intent.lower()
    assert candidates[0].proposer == "calendar_recurrence"
    assert candidates[0].signal["recurrences"] == 2


@pytest.mark.unit
def test_calendar_proposer_ignores_non_recurring():
    fetcher = _FakeCalendarFetcher(
        [
            {"id": "1", "title": "One-off review"},
            {"id": "2", "title": "Flight DL 442"},
        ]
    )
    assert CalendarRecurrenceProposer(fetcher=fetcher).propose("u1") == []


@pytest.mark.unit
def test_propose_candidates_dedups_by_intent():
    class _DupProposer:
        name = "dup"

        def propose(self, user_id):
            return [
                CandidateIntent(raw_intent="same", proposer="dup", rationale="r"),
                CandidateIntent(raw_intent="Same  ", proposer="dup", rationale="r"),
            ]

    candidates = propose_candidates("u1", proposers=(_DupProposer(),))
    assert len(candidates) == 1


@pytest.mark.unit
def test_propose_and_shadow_persists_as_shadow(tmp_path, monkeypatch):
    store = AttentionStore(path=tmp_path / "attentions.json")
    monkeypatch.setattr("donna.attention.propose.AttentionStore", lambda: store)

    fetcher = _FakeCalendarFetcher(
        [
            {"id": "1", "title": "1:1 with Sarah"},
            {"id": "2", "title": "1:1 with Sarah"},
        ]
    )
    proposer = CalendarRecurrenceProposer(fetcher=fetcher)

    # Skip the LLM: force the author to fall back to nearest gold.
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )

    results = asyncio.run(propose_and_shadow("cli-user", proposers=(proposer,)))

    assert len(results) == 1
    persisted = results[0].attention
    assert persisted is not None
    assert persisted.origin is AttentionOrigin.SHADOW_INFERRED
    assert persisted.status is AttentionStatus.SHADOW
    assert persisted.shadow_state is not None

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == persisted.id


@pytest.mark.unit
def test_propose_and_shadow_skips_existing_title(tmp_path, monkeypatch):
    store = AttentionStore(path=tmp_path / "attentions.json")
    monkeypatch.setattr("donna.attention.propose.AttentionStore", lambda: store)

    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )

    fetcher = _FakeCalendarFetcher(
        [{"id": "1", "title": "X"}, {"id": "2", "title": "X"}]
    )
    proposer = CalendarRecurrenceProposer(fetcher=fetcher)

    # First pass authors and persists.
    first = asyncio.run(propose_and_shadow("cli-user", proposers=(proposer,)))
    assert first[0].attention is not None

    # Second pass with the same proposer should detect the duplicate title.
    second = asyncio.run(propose_and_shadow("cli-user", proposers=(proposer,)))
    assert second[0].attention is None
    assert second[0].error == "duplicate_title"
