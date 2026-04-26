"""DeadlineProposer tests."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.propose import DeadlineProposer
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    Subject,
)
from donna.attention.store import AttentionStore
from donna.attention.vocabulary import CardType, SubjectType


@dataclass
class _Loop:
    id: str
    content: str
    due_at: datetime | None
    status: str = "active"


def _in(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def test_no_loops_returns_empty(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    proposer = DeadlineProposer(loop_fetcher=lambda _u: [], store=store)
    assert asyncio.run(proposer.propose("u1")) == []


def test_loop_due_in_2h_emits_high_priority_candidate(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    loops = [_Loop(id="l1", content="send the contract", due_at=_in(2))]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=store)
    candidates = asyncio.run(proposer.propose("u1"))
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.priority == "high"
    assert cand.signal["open_loop_id"] == "l1"


def test_loop_due_in_3_days_skipped(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    loops = [_Loop(id="l1", content="far away", due_at=_in(72))]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=store)
    assert asyncio.run(proposer.propose("u1")) == []


def test_loop_already_passed_skipped(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    loops = [_Loop(id="l1", content="past", due_at=_in(-2))]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=store)
    assert asyncio.run(proposer.propose("u1")) == []


def test_loop_without_due_at_skipped(tmp_path):
    """The whole point — only fires for explicit deadlines."""
    store = AttentionStore(path=tmp_path / "a.json")
    loops = [_Loop(id="l1", content="someday", due_at=None)]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=store)
    assert asyncio.run(proposer.propose("u1")) == []


def test_picks_earliest_when_multiple_due(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    loops = [
        _Loop(id="far", content="distant deadline", due_at=_in(20)),
        _Loop(id="near", content="contract Friday", due_at=_in(2)),
    ]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=store)
    candidates = asyncio.run(proposer.propose("u1"))
    assert len(candidates) == 1
    assert candidates[0].signal["open_loop_id"] == "near"


def test_existing_ping_for_loop_blocks_proposal(tmp_path):
    """If a PING already references the loop's content, skip."""
    base = next(g for g in GOLD_EXAMPLES if g.example_id == "call_mom_ping").spec
    spec = base.model_copy(
        update={
            "title": "contract reminder",
            "description": "ping for: send the contract — due Friday",
            "subject": Subject(name="contract", type=SubjectType.EVENT),
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

    loops = [_Loop(id="l1", content="send the contract", due_at=_in(2))]
    proposer = DeadlineProposer(loop_fetcher=lambda _u: loops, store=_ShimStore())
    assert asyncio.run(proposer.propose("u1")) == []
