"""Lightweight assertions on the prompt's intent-capture rules.

The READ → ACT block enforces the agency split: clocks-named
events get attend(), no-clock vague intentions get
remember(kind="commitment"). Both patterns must be present in the
prompt so the brain has a clear signal for which path to take.
"""
from __future__ import annotations

from donna_runtime.prompt import STAGE_0_5_PROMPT


def test_prompt_has_attend_silently_pattern():
    """Stated future event with a clock → call attend in the same turn."""
    body = STAGE_0_5_PROMPT
    assert "Attend silently" in body or "attend silently" in body.lower()
    # The pattern names the trigger conditions (clock named).
    body_lower = body.lower()
    assert "clock" in body_lower
    assert "exam" in body_lower or "flight" in body_lower or "doctor" in body_lower


def test_prompt_distinguishes_attend_from_commitment():
    """The directive splits clocks-named (attend) from vague (commitment)."""
    body = STAGE_0_5_PROMPT.lower()
    assert "attend" in body
    # Post-retirement the brain uses remember(kind="commitment"), not track_open_loop.
    assert "commitment" in body
    assert "track_open_loop" not in body


def test_prompt_keeps_call_mom_example_for_no_clock_case():
    """The contrasting example with "call mom" prevents the bias from
    collapsing into "always attend"."""
    body = STAGE_0_5_PROMPT.lower()
    assert "call mom" in body


def test_prompt_voice_rules_unchanged():
    """Voice rules around lowercase + no em dashes must still be present."""
    assert "Lowercase" in STAGE_0_5_PROMPT
    assert "em dashes" in STAGE_0_5_PROMPT
