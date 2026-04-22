"""Tests for the shadow → offered promoter."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.promote import (
    PROMOTION_THRESHOLD,
    _is_hit,
    accept_offer,
    reject_offer,
    run_shadow_cycle,
)
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    ShadowState,
)
from donna.attention.store import AttentionStore


def _gold_spec():
    # Use the Poke watcher — event_stream, WhatsApp-mentions source.
    return next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec


def _shadow_attention(user_id=None) -> Attention:
    return Attention(
        user_id=uuid4() if user_id is None else user_id,
        spec=_gold_spec(),
        origin=AttentionOrigin.SHADOW_INFERRED,
        status=AttentionStatus.SHADOW,
        created_at=datetime.now(timezone.utc),
        shadow_state=ShadowState(max_ticks=3),
    )


@pytest.fixture
def store(tmp_path):
    return AttentionStore(path=tmp_path / "attentions.json")


@pytest.mark.unit
def test_is_hit_ignores_empty_sources():
    from donna.attention.dry_run import DryRunResult, SourcePreview
    from donna.attention.vocabulary import CardType, SourceType

    empty = DryRunResult(
        spec_title="t",
        card=CardType.EVENT_STREAM,
        source_previews=(
            SourcePreview(source_type=SourceType.WHATSAPP_MENTIONS_ENTITY, item_count=0, sample=[]),
        ),
        rendered_markdown="",
    )
    assert _is_hit(empty) is False


@pytest.mark.unit
def test_is_hit_ignores_user_elicitation_synthesized_payload():
    from donna.attention.dry_run import DryRunResult, SourcePreview
    from donna.attention.vocabulary import CardType, SourceType

    elicitation_only = DryRunResult(
        spec_title="t",
        card=CardType.PING,
        source_previews=(
            SourcePreview(source_type=SourceType.USER_ELICITATION, item_count=1, sample=[{}]),
        ),
        rendered_markdown="",
    )
    assert _is_hit(elicitation_only) is False


@pytest.mark.unit
def test_shadow_stays_until_max_ticks_or_threshold(store, monkeypatch):
    attention = store.save(_shadow_attention())

    # Force dry_run to return a hit every time.
    from donna.attention.dry_run import DryRunResult, SourcePreview
    from donna.attention.vocabulary import CardType, SourceType

    def hit_preview(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(
                SourcePreview(
                    source_type=SourceType.WHATSAPP_MENTIONS_ENTITY,
                    item_count=1,
                    sample=[{"id": "x"}],
                ),
            ),
            rendered_markdown="hit",
        )

    monkeypatch.setattr("donna.attention.promote.dry_run", hit_preview)

    # First cycle: 1 hit → stays SHADOW (threshold is 2).
    [r1] = run_shadow_cycle(store=store)
    assert r1.to_status is AttentionStatus.SHADOW
    assert r1.action == "stayed"
    assert r1.promotion_hits == 1

    # Second cycle: 2 hits → PROMOTED.
    [r2] = run_shadow_cycle(store=store)
    assert r2.to_status is AttentionStatus.OFFERED
    assert r2.action == "promoted"
    assert r2.promotion_hits == PROMOTION_THRESHOLD

    # Verify persisted.
    refreshed = store.get(attention.id)
    assert refreshed.status is AttentionStatus.OFFERED


@pytest.mark.unit
def test_shadow_archives_when_ticks_exhausted_without_hits(store, monkeypatch):
    store.save(_shadow_attention())

    from donna.attention.dry_run import DryRunResult

    def dry_preview(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(),
            rendered_markdown="empty",
        )

    monkeypatch.setattr("donna.attention.promote.dry_run", dry_preview)

    for _ in range(3):  # max_ticks = 3
        run_shadow_cycle(store=store)

    persisted = store.list()[0]
    assert persisted.status is AttentionStatus.QUIETLY_ARCHIVED
    assert persisted.shadow_state.tick_count == 3
    assert persisted.shadow_state.promotion_hits == 0


@pytest.mark.unit
def test_run_shadow_cycle_ignores_non_shadow(store, monkeypatch):
    attention = _shadow_attention().model_copy(
        update={"status": AttentionStatus.LIVE, "shadow_state": None}
    )
    store.save(attention)

    called = {"n": 0}

    def counting_dry_run(spec, user_id=None):
        called["n"] += 1
        from donna.attention.dry_run import DryRunResult

        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(),
            rendered_markdown="",
        )

    monkeypatch.setattr("donna.attention.promote.dry_run", counting_dry_run)
    results = run_shadow_cycle(store=store)
    assert results == []
    assert called["n"] == 0


@pytest.mark.unit
def test_accept_and_reject_offers(store):
    attention = _shadow_attention().model_copy(update={"status": AttentionStatus.OFFERED})
    store.save(attention)

    accepted = accept_offer(str(attention.id), store=store)
    assert accepted.status is AttentionStatus.LIVE
    assert accepted.shadow_state is None

    # Can't re-accept once it's LIVE.
    assert accept_offer(str(attention.id), store=store) is None

    other = _shadow_attention().model_copy(update={"status": AttentionStatus.OFFERED})
    store.save(other)
    rejected = reject_offer(str(other.id), store=store)
    assert rejected.status is AttentionStatus.REJECTED
