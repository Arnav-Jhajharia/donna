"""Pure-logic tests for user_facts — no DB required."""
from __future__ import annotations

from backend.memory.user_facts.api import resolve_write
from backend.memory.user_facts.rendering import render_living_profile_block, render_user_model_block
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


def test_render_living_profile_includes_situation_brief():
    block = render_living_profile_block(
        {
            "situation_brief": {
                "summary": "shipping memory work",
                "current_status": ["2026-04-22 open_loop: finish memory layer"],
                "last_week": ["2026-04-16 calendar: visa appointment"],
                "next_week": ["2026-04-28 calendar: investor call"],
            }
        }
    )

    assert "SITUATION BRIEF" in block
    assert "shipping memory work" in block
    assert "last week" in block
    assert "visa appointment" in block
    assert "investor call" in block
    # Timestamps and dev-shaped prefixes must not leak into the prompt.
    assert "2026-04-" not in block
    assert "open_loop:" not in block
    assert "calendar:" not in block


def test_render_drops_chat_lines():
    """Chat content is not a fact about the user — it belongs in RECENT CHAT only."""
    block = render_living_profile_block(
        {
            "situation_brief": {
                "summary": "in a stressful week",
                "current_status": [
                    "2026-04-24 chat/user: ur genuinely useless ngl",
                    "2026-04-24 open_loop: finish building donna",
                ],
            }
        }
    )

    assert "ur genuinely useless" not in block
    assert "finish building donna" in block


def test_render_suppresses_boilerplate_summary():
    """Auto-generated dev summaries must not appear as 'summary' in the brief."""
    block = render_living_profile_block(
        {
            "situation_brief": {
                "summary": "Timestamped Postgres evidence grouped into last week, this week, and next week.",
                "current_status": ["2026-04-24 open_loop: finish donna"],
            }
        }
    )

    assert "Timestamped Postgres" not in block
    assert "evidence grouped" not in block
    # The section body should still render cleanly.
    assert "finish donna" in block


def test_render_dedupes_across_sections():
    """The same item (e.g. open loop) must not appear in both current and open threads."""
    block = render_living_profile_block(
        {
            "situation_brief": {
                "current_status": ["2026-04-24 open_loop: finish building donna"],
                "open_loops": ["2026-04-24 open_loop: finish building donna"],
            }
        }
    )

    assert block.lower().count("finish building donna") == 1


def test_render_strips_observation_prefix_but_annotates_type():
    block = render_living_profile_block(
        {
            "situation_brief": {
                "current_status": ["2026-04-24 observation:expense: spent $6 on coffee"],
            }
        }
    )

    assert "observation:expense:" not in block
    # The original expense text already contained "spent $6" — keep it clean.
    assert "spent $6" in block


def test_render_empty_sections_collapse():
    """If every section is chat-only, render empty (no orphan section headers)."""
    block = render_living_profile_block(
        {
            "situation_brief": {
                "current_status": ["2026-04-24 chat/user: lol"],
                "this_week": ["2026-04-24 chat/user: hey"],
            }
        }
    )

    # No section headers should appear since everything was chat.
    assert "right now" not in block
    assert "this week" not in block
