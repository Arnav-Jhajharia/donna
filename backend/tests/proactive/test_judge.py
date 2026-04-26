"""Tier 2 judge — output validation + failure paths.

The Haiku call itself is mocked. We verify schema enforcement, prompt
plumbing, and the failure surface the dispatcher reads.
"""
from __future__ import annotations

import pytest

from proactive.events import ProactiveEvent
from proactive.judge import (
    JudgeOutput,
    JudgeResult,
    _format_event_block,
    _validate_output,
    judge_event,
)


def _event(**kw):
    base = dict(
        user_id="u1",
        source="email",
        source_ref="m1",
        topic_key="thread-A",
        payload={
            "from_address": "luca@antler.co",
            "from_name": "Luca",
            "subject": "thursday or friday?",
            "body_excerpt": "lock in dd call",
        },
        signals={"score": 0.7, "signals": ["biography_relationship"]},
    )
    base.update(kw)
    return ProactiveEvent(**base)


def test_format_event_block_includes_payload_and_signals():
    block = _format_event_block(_event())
    assert "PROACTIVE EVENT" in block
    assert "source: email" in block
    assert "topic_key: thread-A" in block
    assert "from_address: luca@antler.co" in block
    assert "score: 0.7" in block
    assert "biography_relationship" in block


def test_format_event_block_truncates_long_value():
    payload = {"body_excerpt": "x" * 1000}
    event = _event(payload=payload)
    block = _format_event_block(event)
    assert "<truncated>" in block


def test_validate_output_ping_requires_register_and_draft():
    out = JudgeOutput(action="ping", register=None, draft="hi")
    ok, reason = _validate_output(out)
    assert ok is False
    assert reason == "ping_missing_register"


def test_validate_output_ping_requires_draft():
    out = JudgeOutput(action="ping", register="alert", draft="")
    ok, reason = _validate_output(out)
    assert ok is False
    assert reason == "ping_missing_draft"


def test_validate_output_hold_requires_draft():
    out = JudgeOutput(action="hold", register=None, draft=None)
    ok, reason = _validate_output(out)
    assert ok is False
    assert reason == "hold_missing_draft"


def test_validate_output_drop_must_not_have_draft():
    out = JudgeOutput(action="drop", register=None, draft="oops")
    ok, reason = _validate_output(out)
    assert ok is False
    assert reason == "drop_with_draft"


def test_validate_output_register_only_with_ping():
    out = JudgeOutput(action="hold", register="alert", draft="text")
    ok, reason = _validate_output(out)
    assert ok is False
    assert reason == "register_without_ping"


def test_validate_output_happy_path_ping():
    out = JudgeOutput(action="ping", register="alert", draft="luca replied.")
    ok, reason = _validate_output(out)
    assert ok is True
    assert reason is None


def test_validate_output_happy_path_drop():
    out = JudgeOutput(action="drop", register=None, draft=None)
    ok, reason = _validate_output(out)
    assert ok is True


@pytest.mark.asyncio
async def test_judge_event_returns_failed_when_no_api_key(monkeypatch):
    """When no anthropic_api_key is configured the call helper short-circuits."""

    class FakeSettings:
        anthropic_api_key = None

    def _settings():
        return FakeSettings()

    monkeypatch.setattr(
        "backend.config.get_settings",
        _settings,
    )

    # Stub out context loaders to avoid hitting db.
    async def _empty(_user_id):
        return ""

    monkeypatch.setattr("proactive.judge._load_user_model_block", _empty)
    monkeypatch.setattr("proactive.judge._load_today_block", _empty)
    monkeypatch.setattr("proactive.judge._load_recent_chat", _empty)

    result = await judge_event(_event())
    assert isinstance(result, JudgeResult)
    assert result.failed is True
    assert result.failure_reason == "no_api_key"


@pytest.mark.asyncio
async def test_judge_event_parses_successful_call(monkeypatch):
    """Mock _call_haiku to return a parsed JudgeOutput."""

    async def _empty(_user_id):
        return ""

    monkeypatch.setattr("proactive.judge._load_user_model_block", _empty)
    monkeypatch.setattr("proactive.judge._load_today_block", _empty)
    monkeypatch.setattr("proactive.judge._load_recent_chat", _empty)

    parsed = JudgeOutput(
        action="ping",
        register="alert",
        draft="luca replied. wants thursday or friday.",
        tie_in=["antler-dd"],
        needs_tools=False,
        reasoning="active loop",
    )

    async def fake_call(*, system_prompt, user_message):
        return parsed, '{"action":"ping"}'

    monkeypatch.setattr("proactive.judge._call_haiku", fake_call)

    result = await judge_event(_event())
    assert result.failed is False
    assert result.action == "ping"
    assert result.register == "alert"
    assert result.draft.startswith("luca replied")
    assert result.tie_in == ("antler-dd",)


@pytest.mark.asyncio
async def test_judge_event_propagates_schema_violation(monkeypatch):
    async def _empty(_user_id):
        return ""

    monkeypatch.setattr("proactive.judge._load_user_model_block", _empty)
    monkeypatch.setattr("proactive.judge._load_today_block", _empty)
    monkeypatch.setattr("proactive.judge._load_recent_chat", _empty)

    parsed = JudgeOutput(
        action="ping", register=None, draft="not allowed without register"
    )

    async def fake_call(*, system_prompt, user_message):
        return parsed, "raw"

    monkeypatch.setattr("proactive.judge._call_haiku", fake_call)

    result = await judge_event(_event())
    assert result.failed is True
    assert result.failure_reason == "ping_missing_register"
