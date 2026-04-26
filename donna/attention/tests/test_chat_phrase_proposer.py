"""ChatPhraseProposer (drinking-signal -> hydration) tests.

Stays at the proposer layer — covers the regex, the dedup against
existing hydration attentions, and the candidate shape. End-to-end
flow (proposer -> SHADOW row) is exercised in propose_and_shadow tests.

``propose`` is async (the production fetcher does DB I/O via asyncpg,
which is loop-bound), so each test invokes it via ``asyncio.run``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.propose import (
    ChatPhraseProposer,
    _DRINKING_PATTERN,
    _first_drinking_hit,
)
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    AttentionSpec,
    Subject,
)
from donna.attention.store import AttentionStore
from donna.attention.vocabulary import CardType, SubjectType


@dataclass
class _Msg:
    role: str
    content: str
    created_at: datetime


def _user_msg(text: str, *, when: datetime | None = None) -> _Msg:
    return _Msg(
        role="user",
        content=text,
        created_at=when or datetime.now(timezone.utc),
    )


def _assistant_msg(text: str) -> _Msg:
    return _Msg(role="assistant", content=text, created_at=datetime.now(timezone.utc))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ended up drinking too much last night", True),
        ("hungover this morning", True),
        ("drank way too much", True),
        ("rough morning", True),
        ("hammered last night, never again", True),
        ("drinking water before the run", False),
        ("keep drinking water", False),
        ("reminder: drink lots of water", False),
        ("I drank a glass of water", False),
        ("rocking through the day", False),
    ],
)
def test_drinking_pattern_matches_signal_only(text, expected):
    assert bool(_DRINKING_PATTERN.search(text)) is expected


def test_first_drinking_hit_returns_first_user_match():
    msgs = [
        _user_msg("morning, just had toast"),
        _assistant_msg("hungover from last night"),  # assistant — must be skipped
        _user_msg("ended up drinking too much last night"),
        _user_msg("rough morning"),
    ]
    hit = _first_drinking_hit(msgs)
    assert hit is not None
    assert "drinking" in hit["matched"] or "ended up" in hit["text"].lower()
    # must be the first USER hit, not the assistant line
    assert "ended up" in hit["text"].lower()


def test_first_drinking_hit_returns_none_when_no_match():
    msgs = [
        _user_msg("morning, just had toast"),
        _user_msg("standup at 9"),
    ]
    assert _first_drinking_hit(msgs) is None


def test_proposer_emits_one_candidate_on_hit(tmp_path):
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [
            _user_msg("ended up drinking too much last night, feel like trash"),
            _user_msg("standup at 9"),
        ]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=store)
    candidates = asyncio.run(proposer.propose(user_id))
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.proposer == "chat_phrase"
    assert "hydration" in cand.raw_intent.lower()
    assert "tally" in cand.raw_intent.lower()
    assert cand.priority == "medium"
    assert "phrase_excerpt" in cand.signal


def test_proposer_skips_when_no_drinking_signal(tmp_path):
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [
            _user_msg("morning, just had toast"),
            _user_msg("standup at 9"),
        ]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=store)
    assert asyncio.run(proposer.propose(user_id)) == []


def test_proposer_skips_assistant_only_signal(tmp_path):
    """Assistant-side mention of drinking must not fire the proposer."""
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [_assistant_msg("you mentioned drinking too much last night")]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=store)
    assert asyncio.run(proposer.propose(user_id)) == []


def _hydration_spec() -> AttentionSpec:
    """Build a spec mentioning hydration so the dedup branch fires."""
    base = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    return base.model_copy(
        update={
            "title": "hydration tracker",
            "description": "count glasses of water toward a 2L target",
            "subject": Subject(name="hydration", type=SubjectType.SELF),
            "card": CardType.TALLY,
        }
    )


def test_proposer_dedups_against_offered_hydration(tmp_path):
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")
    existing = Attention(
        user_id=uuid4(),  # store.list filter is by user_id below
        spec=_hydration_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.OFFERED,
        created_at=datetime.now(timezone.utc),
    )
    # Force user_id to match.
    existing = existing.model_copy(update={"user_id": uuid4()})
    # Easier: monkey-patch store.list to return our existing row when
    # asked for this user.
    store.save(existing.model_copy(update={"user_id": existing.user_id}))

    # Wire the proposer with a custom store.list shim that returns the
    # existing hydration attention regardless of the user_id passed.
    class _ShimStore:
        def list(self, user_id=None, status=None):  # noqa: A002
            return [existing]

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [_user_msg("hungover this morning")]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=_ShimStore())
    assert asyncio.run(proposer.propose(user_id)) == []


def test_proposer_dedups_against_live_hydration(tmp_path):
    user_id = str(uuid4())
    existing = Attention(
        user_id=uuid4(),
        spec=_hydration_spec(),
        origin=AttentionOrigin.OFFER_ACCEPTED,
        status=AttentionStatus.LIVE,
        created_at=datetime.now(timezone.utc),
    )

    class _ShimStore:
        def list(self, user_id=None, status=None):  # noqa: A002
            return [existing]

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [_user_msg("hammered last night")]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=_ShimStore())
    assert asyncio.run(proposer.propose(user_id)) == []


def test_proposer_does_not_dedup_against_rejected(tmp_path):
    """A REJECTED attention is not "in flight" — proposer may re-fire."""
    user_id = str(uuid4())
    existing = Attention(
        user_id=uuid4(),
        spec=_hydration_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.REJECTED,
        created_at=datetime.now(timezone.utc),
    )

    class _ShimStore:
        def list(self, user_id=None, status=None):  # noqa: A002
            return [existing]

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return [_user_msg("hungover")]

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=_ShimStore())
    candidates = asyncio.run(proposer.propose(user_id))
    assert len(candidates) == 1
