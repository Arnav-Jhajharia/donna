"""Tier 3 fat-contract context builder — 11 blocks rendered into one prompt."""
from __future__ import annotations

import pytest

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult
from donna_runtime.context_builder_tier3 import build_tier3_user_message


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet",
        tie_in=("luca",),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


def _event() -> ProactiveEvent:
    return ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_abc",
        topic_key="thread_xyz",
        speech_act="heads_up",
        payload={
            "from_address": "luca@x.com",
            "subject": "term sheet v2",
            "body_excerpt": "see attached",
        },
        signals={"score": 0.8, "event_age_minutes": 30},
    )


def test_build_tier3_user_message_includes_all_block_headers():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="USER MODEL: arnav, building donna",
        day_view_block="DAY VIEW: nothing yet today",
        prior_touches_block="PRIOR TOUCHES: none",
        user_state_block="USER STATE: focused, in engage window",
        pending_notes_block="PENDING NOTES: none",
        queued_thing_block="QUEUED THING: <attention spec>",
        fresh_signal_block=None,
    )
    for header in (
        "WHY YOU'RE AWAKE",
        "USER MODEL",
        "THE QUEUED THING",
        "THE EVENT PAYLOAD",
        "TIER 2",
        "DAY VIEW",
        "PRIOR TOUCHES",
        "USER STATE NOW",
        "PENDING NOTES",
    ):
        assert header in msg, f"missing block header: {header}"


def test_build_tier3_user_message_excludes_fresh_signal_when_none():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "FRESH SIGNAL" not in msg


def test_build_tier3_user_message_includes_fresh_signal_when_present():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block="FRESH SIGNAL: thread has 2 new replies since trigger",
    )
    assert "FRESH SIGNAL" in msg
    assert "2 new replies" in msg


def test_build_tier3_user_message_renders_speech_act_and_reason():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="stakes_aware",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "speech_act: heads_up" in msg
    assert "escalation_reason: stakes_aware" in msg


def test_build_tier3_user_message_renders_tier2_with_optional_fields():
    """channel_hint and reclassify_speech_act render when set."""
    judge = JudgeResult(
        action="ping",
        register="soft",
        draft="hey",
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response="",
        channel_hint="dashboard",
        reclassify_speech_act="i_noticed",
    )
    msg = build_tier3_user_message(
        event=_event(),
        judge=judge,
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "channel_hint: dashboard" in msg
    assert "reclassify_speech_act: i_noticed" in msg


def test_build_tier3_user_message_truncates_long_payload_values():
    """Strings over 600 chars get a trailing ellipsis to bound the prompt."""
    long = "x" * 1000
    event = ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="r",
        topic_key="t",
        speech_act="heads_up",
        payload={"body_excerpt": long},
    )
    msg = build_tier3_user_message(
        event=event,
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    # The line for body_excerpt is bounded; full 1000-char value is not in the
    # output verbatim.
    assert ("x" * 1000) not in msg


def test_build_tier3_user_message_omits_register_when_none():
    """register: line is omitted when judge.register is None
    (consistent with channel_hint and reclassify_speech_act handling)."""
    judge = JudgeResult(
        action="drop",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="not interesting",
        raw_response="",
    )
    msg = build_tier3_user_message(
        event=_event(),
        judge=judge,
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "register:" not in msg
    assert "n/a" not in msg


def test_escalation_reason_imported_from_proactive_events():
    """EscalationReason should be importable from proactive.events
    so the dispatcher (Task 11) doesn't need type: ignore."""
    from proactive.events import EscalationReason  # noqa: F401
    from proactive import EscalationReason as EscalationReasonRoot  # noqa: F401
