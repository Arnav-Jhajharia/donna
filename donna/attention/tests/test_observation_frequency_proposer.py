"""ObservationFrequencyProposer tests.

Stub the observation fetcher + store so tests run hermetically.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.propose import ObservationFrequencyProposer
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    Subject,
)
from donna.attention.store import AttentionStore
from donna.attention.vocabulary import CardType, SubjectType


@dataclass
class _Obs:
    type: str
    event_time: datetime


def _now(offset_days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=offset_days)


def test_no_observations_returns_empty(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: [], store=store
    )
    assert asyncio.run(proposer.propose("u1")) == []


def test_below_threshold_returns_empty(tmp_path):
    """Two coffees in a week → not enough."""
    store = AttentionStore(path=tmp_path / "a.json")
    obs = [
        _Obs(type="coffee", event_time=_now(0.5)),
        _Obs(type="coffee", event_time=_now(2.5)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=store
    )
    assert asyncio.run(proposer.propose("u1")) == []


def test_three_coffees_within_window_emits_candidate(tmp_path):
    """Three coffees with median gap 2 days → propose tracking coffee."""
    store = AttentionStore(path=tmp_path / "a.json")
    obs = [
        _Obs(type="coffee", event_time=_now(5)),
        _Obs(type="coffee", event_time=_now(3)),
        _Obs(type="coffee", event_time=_now(1)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=store
    )
    candidates = asyncio.run(proposer.propose("u1"))
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.proposer == "observation_frequency"
    assert "coffee" in cand.raw_intent.lower()
    assert "tally" in cand.raw_intent.lower()
    assert cand.signal["obs_type"] == "coffee"
    assert cand.signal["count_in_window"] == 3


def test_existing_tracker_blocks_proposal(tmp_path):
    """If a coffee tracker is already LIVE, don't re-propose."""
    store = AttentionStore(path=tmp_path / "a.json")
    base = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    spec = base.model_copy(
        update={
            "title": "coffee tracker",
            "description": "track coffee daily",
            "subject": Subject(name="coffee", type=SubjectType.SELF),
            "card": CardType.TALLY,
        }
    )
    a = Attention(
        user_id=uuid4(),
        spec=spec,
        origin=AttentionOrigin.USER_EXPLICIT,
        status=AttentionStatus.LIVE,
        created_at=datetime.now(timezone.utc),
    )

    class _ShimStore:
        def list(self, user_id=None, status=None):
            return [a]

    obs = [
        _Obs(type="coffee", event_time=_now(5)),
        _Obs(type="coffee", event_time=_now(3)),
        _Obs(type="coffee", event_time=_now(1)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=_ShimStore()
    )
    assert asyncio.run(proposer.propose("u1")) == []


def test_system_obs_types_skipped(tmp_path):
    """Calendar/document obs are system signals, not user habits."""
    store = AttentionStore(path=tmp_path / "a.json")
    obs = [
        _Obs(type="document", event_time=_now(5)),
        _Obs(type="document", event_time=_now(3)),
        _Obs(type="document", event_time=_now(1)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=store
    )
    assert asyncio.run(proposer.propose("u1")) == []


def test_wide_gap_skipped(tmp_path):
    """Three obs spread across 14 days = median gap 7d → skip."""
    store = AttentionStore(path=tmp_path / "a.json")
    obs = [
        _Obs(type="meal", event_time=_now(14)),
        _Obs(type="meal", event_time=_now(7)),
        _Obs(type="meal", event_time=_now(0)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=store
    )
    assert asyncio.run(proposer.propose("u1")) == []


def test_picks_most_frequent_when_multiple_qualify(tmp_path):
    """Coffee × 4 vs meal × 3 in same window → coffee wins."""
    store = AttentionStore(path=tmp_path / "a.json")
    obs = [
        _Obs(type="coffee", event_time=_now(5)),
        _Obs(type="coffee", event_time=_now(3)),
        _Obs(type="coffee", event_time=_now(1.5)),
        _Obs(type="coffee", event_time=_now(0.5)),
        _Obs(type="meal", event_time=_now(4)),
        _Obs(type="meal", event_time=_now(2)),
        _Obs(type="meal", event_time=_now(0)),
    ]
    proposer = ObservationFrequencyProposer(
        observation_fetcher=lambda _u, _d: obs, store=store
    )
    candidates = asyncio.run(proposer.propose("u1"))
    assert len(candidates) == 1
    assert candidates[0].signal["obs_type"] == "coffee"
    assert candidates[0].signal["count_in_window"] == 4
