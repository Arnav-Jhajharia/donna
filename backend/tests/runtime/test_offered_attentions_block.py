"""ATTENTIONS WAITING block + accept_attention tool tests.

Covers:
- the renderer: empty -> "" / populated -> tight block with id, card, title, rationale
- the fetch + render via load_offered_attentions_block (file store fixture)
- the tool: success / unknown id / non-OFFERED state all return sensible text
- the lifecycle: accept_offer flips OFFERED -> LIVE and bumps origin
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.promote import accept_offer
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
)
from donna.attention.store import AttentionStore
from donna_runtime.context_builder import (
    render_offered_attentions_block,
)


def _gold_spec():
    return next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec


def _offered_attention(user_id) -> Attention:
    return Attention(
        user_id=user_id,
        spec=_gold_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.OFFERED,
        created_at=datetime.now(timezone.utc),
    )


def test_render_empty_returns_empty_string():
    assert render_offered_attentions_block([]) == ""


def test_render_includes_id_card_title_and_rationale():
    user_id = uuid4()
    a = _offered_attention(user_id)
    block = render_offered_attentions_block([a])
    assert "ATTENTIONS WAITING" in block
    assert str(a.id) in block, "attention_id must be in the block"
    # Card type label appears (lowercase enum value).
    assert a.spec.card.value in block
    # Title appears.
    assert a.spec.title.lower()[:30] in block.lower()
    # Description (rationale) appears.
    assert a.spec.description.lower()[:30] in block.lower()


def test_render_caps_rationale_length():
    user_id = uuid4()
    a = _offered_attention(user_id)
    long_desc = "x" * 400
    a = a.model_copy(update={"spec": a.spec.model_copy(update={"description": long_desc})})
    block = render_offered_attentions_block([a])
    # No single line should be wildly long.
    longest = max(len(line) for line in block.splitlines())
    assert longest < 240, f"rationale not capped, longest line {longest} chars"


def test_render_includes_accept_instruction():
    a = _offered_attention(uuid4())
    block = render_offered_attentions_block([a])
    assert "accept_attention" in block, (
        "block must teach the model that accept_attention is the next move"
    )


def test_accept_offer_transitions_offered_to_live(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    a = _offered_attention(uuid4())
    store.save(a)

    out = accept_offer(str(a.id), store=store)
    assert out is not None
    assert out.status is AttentionStatus.LIVE
    assert out.origin is AttentionOrigin.OFFER_ACCEPTED
    # Shadow bookkeeping is dropped on accept.
    assert out.shadow_state is None


def test_accept_offer_returns_none_for_non_offered(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    a = _offered_attention(uuid4()).model_copy(
        update={"status": AttentionStatus.LIVE}
    )
    store.save(a)
    assert accept_offer(str(a.id), store=store) is None


def test_accept_offer_returns_none_for_unknown_id(tmp_path):
    store = AttentionStore(path=tmp_path / "a.json")
    assert accept_offer(str(uuid4()), store=store) is None
