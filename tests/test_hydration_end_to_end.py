"""Hydration loop — end-to-end proof.

Walks the seams the user named in plan: drinking signal in chat ->
SHADOW attention (TALLY) -> promote to OFFERED on hit -> dashboard
composer surfaces it -> ATTENTIONS WAITING block renders it -> accept
flips OFFERED to LIVE and materializes a DonnaInstance.

The LLM authoring step (``run_attention_pipeline``) is bypassed via a
hand-rolled SHADOW attention — that step is exercised in the existing
attention authoring tests. Every other seam is real code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from backend.dashboard import actions as dba
from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.promote import accept_offer
from donna.attention.propose import (
    ChatPhraseProposer,
    _DRINKING_PATTERN,
)
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionSpec,
    AttentionStatus,
    ShadowState,
    Subject,
)
from donna.attention.store import AttentionStore
from donna.attention.vocabulary import CardType, SubjectType
from donna_runtime.context_builder import (
    render_offered_attentions_block,
)


@dataclass
class _Msg:
    role: str
    content: str
    created_at: datetime


def _hydration_spec() -> AttentionSpec:
    """Hydration TALLY spec — what run_attention_pipeline would author
    for a chat-phrase candidate."""
    base = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    return base.model_copy(
        update={
            "title": "hydration tracker (today)",
            "description": (
                "count glasses of water toward a 2L target — flagged because "
                "of last night's drinking signal"
            ),
            "subject": Subject(name="hydration", type=SubjectType.SELF),
            "card": CardType.TALLY,
        }
    )


def _wire_store(monkeypatch, store: AttentionStore) -> None:
    factory = lambda *_a, **_kw: store  # noqa: E731
    monkeypatch.setattr("donna.attention.store.AttentionStore", factory)
    monkeypatch.setattr("donna.attention.promote.AttentionStore", factory)
    monkeypatch.setattr("donna.attention.tools.AttentionStore", factory)


@pytest.mark.asyncio
async def test_hydration_end_to_end_seam_walk(monkeypatch, tmp_path):
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)

    # ─── seam 1 ────────────────────────────────────────────────────────────
    # User message "ended up drinking too much last night" hits the regex.
    chat_messages = [
        _Msg(
            role="user",
            content="ended up drinking too much last night, feel like trash",
            created_at=datetime.now(timezone.utc),
        ),
    ]

    def fake_chat(_uid: str, _hours: int) -> list[Any]:
        return list(chat_messages)

    proposer = ChatPhraseProposer(chat_fetcher=fake_chat, store=store)
    candidates = await proposer.propose(user_id)
    assert len(candidates) == 1, "drinking signal must yield one candidate"
    assert "hydration" in candidates[0].raw_intent.lower()

    # ─── seam 2 ────────────────────────────────────────────────────────────
    # Stand in for the LLM authoring step: hand-build a SHADOW attention
    # with the hydration spec and persist it.
    attention = Attention(
        user_id=uuid4(),  # gets overwritten just below for this user
        spec=_hydration_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.SHADOW,
        created_at=datetime.now(timezone.utc),
        shadow_state=ShadowState(max_ticks=3, promotion_hits=0, tick_count=0),
    )
    # Pin to the test user_id (Attention.user_id is a UUID, not a str).
    from uuid import UUID

    attention = attention.model_copy(update={"user_id": UUID(user_id)})
    store.save(attention)

    rows = store.list(user_id=user_id, status=AttentionStatus.SHADOW)
    assert len(rows) == 1, "SHADOW attention must persist for this user"

    # ─── seam 3 ────────────────────────────────────────────────────────────
    # Promote: simulate a hit by bumping the shadow row to OFFERED. The
    # existing run_shadow_cycle uses a dry-run preview; that path is
    # exercised in test_promote.py — here we want to verify what happens
    # AFTER the row is OFFERED, so the manual flip is fine.
    store.save(rows[0].model_copy(update={"status": AttentionStatus.OFFERED}))

    offered = store.list(user_id=user_id, status=AttentionStatus.OFFERED)
    assert len(offered) == 1, "must land in OFFERED after promote"

    # ─── seam 4 ────────────────────────────────────────────────────────────
    # The brain's per-turn context renders the OFFERED row in
    # ATTENTIONS WAITING. That block has the attention_id and tells the
    # model how to accept.
    block = render_offered_attentions_block(offered)
    assert "ATTENTIONS WAITING" in block
    assert str(offered[0].id) in block
    assert "tally" in block.lower()
    assert "hydration" in block.lower()
    assert "accept_attention" in block

    # ─── seam 5 ────────────────────────────────────────────────────────────
    # Dashboard accept: POST /action invokes
    # ``accept_offered_attention`` which flips status, materializes a
    # DonnaInstance for TALLY, and recomposes the manifest.
    materialize_calls: list[str] = []
    recompose_calls: list[str] = []

    async def fake_materialize(*, user_id: str, attention: Any):
        # Prove the function gets called for a TALLY card.
        assert attention.spec.card is CardType.TALLY
        materialize_calls.append(str(attention.id))
        return ("inst-hydration", True)

    def fake_spawn(*, user_id: str):
        recompose_calls.append(user_id)
        return "scheduled"

    monkeypatch.setattr(dba, "_maybe_materialize_instance", fake_materialize)
    monkeypatch.setattr(dba, "_spawn_recompose", fake_spawn)

    result = await dba.accept_offered_attention(
        user_id=user_id, attention_id=str(offered[0].id)
    )

    assert result.ok is True, result.error
    assert result.status == "live"
    assert result.instance_id == "inst-hydration"
    assert result.instance_created is True
    assert result.recomposed == "scheduled"
    assert materialize_calls == [str(offered[0].id)]
    assert recompose_calls == [user_id]

    # ─── seam 6 ────────────────────────────────────────────────────────────
    # After accept: status is LIVE, origin reflects the path taken.
    refreshed = store.get(offered[0].id)
    assert refreshed.status is AttentionStatus.LIVE
    assert refreshed.origin is AttentionOrigin.OFFER_ACCEPTED

    # OFFERED is now empty → ATTENTIONS WAITING block renders empty.
    still_offered = store.list(
        user_id=user_id, status=AttentionStatus.OFFERED
    )
    assert still_offered == []
    assert render_offered_attentions_block(still_offered) == ""


@pytest.mark.asyncio
async def test_double_accept_is_idempotent_no_op(monkeypatch, tmp_path):
    """If the user taps Accept twice (race / double-fire), the second
    call must not flip anything and must not materialize a duplicate."""
    user_id = str(uuid4())
    store = AttentionStore(path=tmp_path / "a.json")
    _wire_store(monkeypatch, store)

    monkeypatch.setattr(
        dba,
        "_maybe_materialize_instance",
        lambda **_: __import__("asyncio").sleep(0, result=("inst", True)),
    )
    monkeypatch.setattr(dba, "_spawn_recompose", lambda **_: "scheduled")

    from uuid import UUID

    a = Attention(
        user_id=UUID(user_id),
        spec=_hydration_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.OFFERED,
        created_at=datetime.now(timezone.utc),
    )
    store.save(a)

    first = await dba.accept_offered_attention(
        user_id=user_id, attention_id=str(a.id)
    )
    assert first.ok is True

    second = await dba.accept_offered_attention(
        user_id=user_id, attention_id=str(a.id)
    )
    assert second.ok is False
    assert second.error == "attention is not OFFERED"


def test_drinking_regex_does_not_misfire_on_hydration_speak():
    """If the user is talking ABOUT hydration ("keep drinking water"),
    the proposer must not fire — that would be circular."""
    msgs_that_should_not_fire = [
        "drinking water before the run",
        "keep drinking water through the day",
        "I drank a glass of water with breakfast",
        "remember to hydrate, drinking enough is hard for me",
    ]
    for text in msgs_that_should_not_fire:
        assert _DRINKING_PATTERN.search(text) is None, (
            f"regex misfired on hydration-positive text: {text!r}"
        )
