"""ProactiveEvent envelope — speech_act field and system_b_web source."""
from __future__ import annotations

import pytest

from proactive.events import ProactiveEvent, SpeechAct


def test_proactive_event_carries_speech_act():
    event = ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_abc",
        topic_key="thread_xyz",
        speech_act="heads_up",
        payload={"from_address": "luca@x.com"},
    )
    assert event.speech_act == "heads_up"


def test_proactive_event_speech_act_defaults_to_thought_youd_want():
    """Back-compat default keeps unmigrated callers working in Phase 1."""
    event = ProactiveEvent(
        user_id="u1",
        source="attention_fire",
        source_ref="att_1",
        topic_key="att_1",
    )
    assert event.speech_act == "thought_youd_want"


def test_speech_act_allows_five_canonical_values():
    valid: list[SpeechAct] = [
        "dont_forget",
        "heads_up",
        "i_noticed",
        "now_the_moment",
        "thought_youd_want",
    ]
    for sa in valid:
        e = ProactiveEvent(
            user_id="u1",
            source="email",
            source_ref="r",
            topic_key="t",
            speech_act=sa,
        )
        assert e.speech_act == sa


def test_proactive_source_includes_system_b_web():
    event = ProactiveEvent(
        user_id="u1",
        source="system_b_web",
        source_ref="https://example.com/post",
        topic_key="sysb:example.com:abc",
        speech_act="thought_youd_want",
    )
    assert event.source == "system_b_web"
