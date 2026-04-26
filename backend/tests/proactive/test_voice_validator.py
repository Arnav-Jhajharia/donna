"""Deterministic voice net for Tier 2 drafts."""
from __future__ import annotations

from proactive.voice_validator import apply_mechanical_strips, validate


def test_clean_text_passes():
    result = validate("luca replied. wants thursday 4pm or friday morning.")
    assert result.ok is True
    assert result.reasons == ()
    assert result.cleaned == "luca replied. wants thursday 4pm or friday morning."


def test_em_dash_stripped_and_marked():
    result = validate("luca replied — wants thursday 4pm.")
    assert result.ok is True
    assert "em_dash" in result.reasons
    assert "—" not in result.cleaned
    assert "  " not in result.cleaned  # double-space collapsed


def test_short_dash_also_stripped():
    result = validate("noted – will follow up.")
    assert result.ok is True
    assert "em_dash" in result.reasons
    assert "–" not in result.cleaned


def test_semicolon_replaced_with_period():
    result = validate("got it; will revert tomorrow.")
    assert result.ok is True
    assert "semicolon" in result.reasons
    assert ";" not in result.cleaned
    assert "." in result.cleaned


def test_emoji_flagged_not_repaired():
    result = validate("nice 😀 sounds good.")
    assert result.ok is False
    assert "emoji" in result.reasons


def test_excessive_uppercase_flagged():
    result = validate("YOU REALLY NEED TO RESPOND TO LUCA NOW.")
    assert result.ok is False
    assert "uppercase_ratio" in result.reasons


def test_proper_nouns_below_threshold_pass():
    text = "luca at antler replied. wants thursday or friday for the dd call."
    result = validate(text)
    assert result.ok is True


def test_combined_emoji_and_dash_returns_emoji_violation():
    result = validate("done — 🎉")
    # em-dash strippable but emoji is hard fail.
    assert result.ok is False
    assert "emoji" in result.reasons


def test_apply_mechanical_strips_idempotent():
    once = apply_mechanical_strips("a — b ; c")
    twice = apply_mechanical_strips(once)
    assert once == twice
    assert "—" not in once
    assert ";" not in once
