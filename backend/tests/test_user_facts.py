"""Pure-logic tests for user_facts — no DB required."""
from __future__ import annotations

from backend.memory.user_facts.api import resolve_write
from backend.memory.user_facts.rendering import render_user_model_block
from backend.memory.user_facts.schema import (
    Confidence,
    DEFAULT_FACTS,
    FactKey,
    Source,
    confidence_rank,
    is_valid_fact_key,
    source_rank,
)


def test_fact_key_validation():
    assert is_valid_fact_key("preferred_name")
    assert not is_valid_fact_key("not_a_key")


def test_confidence_and_source_ranks():
    assert confidence_rank("high") > confidence_rank("low")
    assert source_rank(Source.USER_CORRECTION.value) > source_rank(Source.DEFAULT.value)


def test_resolve_no_existing_writes():
    fact = resolve_write(None, "Arnav", Source.ONBOARDING_EXPLICIT, Confidence.HIGH)
    assert fact["value"] == "Arnav"
    assert fact["source"] == Source.ONBOARDING_EXPLICIT.value


def test_user_correction_always_wins():
    existing = {
        "value": "old",
        "source": Source.ONBOARDING_EXPLICIT.value,
        "confidence": Confidence.HIGH.value,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    new = resolve_write(existing, "new", Source.USER_CORRECTION, Confidence.LOW)
    assert new["value"] == "new"


def test_higher_confidence_wins():
    existing = {
        "value": "a",
        "source": Source.CONVERSATION_INFERRED.value,
        "confidence": Confidence.LOW.value,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    new = resolve_write(existing, "b", Source.CONVERSATION_EXTRACTED, Confidence.HIGH)
    assert new["value"] == "b"


def test_lower_confidence_keeps_existing():
    existing = {
        "value": "a",
        "source": Source.USER_CORRECTION.value,
        "confidence": Confidence.HIGH.value,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    new = resolve_write(existing, "b", Source.CONVERSATION_INFERRED, Confidence.LOW)
    assert new["value"] == "a"


def test_same_confidence_source_rank_breaks_tie():
    existing = {
        "value": "a",
        "source": Source.CONVERSATION_INFERRED.value,
        "confidence": Confidence.MEDIUM.value,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    new = resolve_write(existing, "b", Source.CONVERSATION_EXTRACTED, Confidence.MEDIUM)
    assert new["value"] == "b"


def test_default_facts_seed():
    seed = DEFAULT_FACTS()
    assert FactKey.PRIMARY_LANGUAGE.value in seed


def test_render_empty_facts_is_empty():
    assert render_user_model_block({}) == ""


def test_render_default_only_is_empty():
    facts = DEFAULT_FACTS()
    assert render_user_model_block(facts) == ""


def test_render_with_signal_shows_block():
    facts = {
        FactKey.PREFERRED_NAME.value: {
            "value": "Arnav",
            "source": Source.ONBOARDING_EXPLICIT.value,
            "confidence": Confidence.HIGH.value,
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }
    block = render_user_model_block(facts)
    assert "USER MODEL" in block
    assert "Arnav" in block
