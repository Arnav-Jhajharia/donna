"""Lightweight assertions on the in-turn intent-capture prompt change.

The full eval-suite test (does the brain actually call attend on a concrete
future utterance?) is deferred — that needs the full SDK loop and a recorded
trace. This test pins the prompt language so a regression is loud at unit-test
time.
"""
from __future__ import annotations

import pytest

from donna_runtime.prompt import STAGE_0_5_PROMPT


def test_prompt_has_concrete_event_capture_section():
    assert "CAPTURING CONCRETE FUTURE COMMITMENTS" in STAGE_0_5_PROMPT


def test_prompt_distinguishes_attend_from_open_loop():
    body = STAGE_0_5_PROMPT.lower()
    # The directive must explicitly mention attend vs track_open_loop.
    assert "attend" in body
    assert "track_open_loop" in body
    # The bias for stated-time events must be explicit.
    assert "without asking" in body or "without asking." in body


@pytest.mark.parametrize(
    "phrase",
    [
        "midterm",
        "flight friday",
        "dentist wednesday",
    ],
)
def test_prompt_carries_at_least_three_voice_examples(phrase):
    assert phrase.lower() in STAGE_0_5_PROMPT.lower()


def test_prompt_keeps_open_loop_for_vague_intentions():
    # The contrasting example with "call mom" prevents the bias from
    # collapsing into "always attend, never track_open_loop".
    assert "call mom" in STAGE_0_5_PROMPT.lower()


def test_prompt_voice_rules_unchanged():
    """Voice rules around lowercase + no em dashes must still be present."""
    assert "Lowercase" in STAGE_0_5_PROMPT
    assert "em dashes" in STAGE_0_5_PROMPT
