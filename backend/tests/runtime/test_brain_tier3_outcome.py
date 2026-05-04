"""Phase 2.5 plumbing: brain extracts Tier 3 terminator into _tier3_outcome."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from donna_runtime.brain import (
    _TIER3_TERMINATORS,
    _extract_tier3_outcome,
    _normalize_send_burst_messages,
    _strip_mcp_prefix,
)


def _trace_with_calls(*calls: dict) -> SimpleNamespace:
    """Build a minimal trace stub with just .tool_calls."""
    return SimpleNamespace(tool_calls=list(calls))


def _call(tool: str, **inputs) -> dict:
    return {"tool": tool, "inputs": inputs}


def test_strip_mcp_prefix_namespaced():
    assert _strip_mcp_prefix("mcp__donna__send_burst") == "send_burst"


def test_strip_mcp_prefix_already_short():
    assert _strip_mcp_prefix("send_burst") == "send_burst"


def test_extract_returns_none_when_trace_is_none():
    assert _extract_tier3_outcome(None) is None


def test_extract_returns_none_when_no_terminator():
    trace = _trace_with_calls(
        _call("mcp__donna__quick_check", question="what's the weather"),
        _call("mcp__donna__read_external", source="gmail_thread", ref="t_1"),
    )
    assert _extract_tier3_outcome(trace) is None


def test_extract_send_burst_returns_ship_with_normalized_messages():
    trace = _trace_with_calls(
        _call(
            "mcp__donna__send_burst",
            messages=[{"type": "text", "text": "luca replied"}],
            push=True,
        )
    )
    outcome = _extract_tier3_outcome(trace)
    assert outcome == {
        "action": "ship",
        "messages": [{"type": "text", "text": "luca replied", "body": "luca replied"}],
        "push": True,
    }


def test_extract_send_burst_preserves_existing_body():
    """If a message already has 'body', we leave it alone."""
    trace = _trace_with_calls(
        _call(
            "mcp__donna__send_burst",
            messages=[{"type": "text", "body": "already here", "text": "ignored"}],
        )
    )
    outcome = _extract_tier3_outcome(trace)
    assert outcome["messages"][0]["body"] == "already here"


def test_extract_skip_returns_skip_with_reason():
    trace = _trace_with_calls(
        _call("mcp__donna__skip", reason="user already replied in chat")
    )
    assert _extract_tier3_outcome(trace) == {
        "action": "skip",
        "reason": "user already replied in chat",
    }


def test_extract_kill_attention_returns_kill():
    trace = _trace_with_calls(
        _call(
            "mcp__donna__kill_attention",
            attention_id="att_1",
            reason="moot now",
        )
    )
    assert _extract_tier3_outcome(trace) == {
        "action": "kill",
        "attention_id": "att_1",
        "reason": "moot now",
    }


def test_extract_reshape_returns_reshape():
    trace = _trace_with_calls(
        _call(
            "mcp__donna__reshape_attention",
            attention_id="att_1",
            next_fire_at="2026-05-06T08:00:00",
        )
    )
    assert _extract_tier3_outcome(trace) == {
        "action": "reshape",
        "attention_id": "att_1",
        "next_fire_at": "2026-05-06T08:00:00",
    }


def test_extract_returns_last_terminator_when_multiple():
    """If the model called two terminators (rare but possible), the last one wins."""
    trace = _trace_with_calls(
        _call("mcp__donna__skip", reason="first thought"),
        _call(
            "mcp__donna__send_burst",
            messages=[{"type": "text", "text": "actually ping them"}],
            push=True,
        ),
    )
    outcome = _extract_tier3_outcome(trace)
    assert outcome is not None
    assert outcome["action"] == "ship"


def test_extract_ignores_non_terminator_tools_between_terminator_calls():
    """Quick_check / read_external are NOT terminators — extractor skips them."""
    trace = _trace_with_calls(
        _call("mcp__donna__skip", reason="first decision"),
        _call("mcp__donna__quick_check", question="any news?"),
        _call("mcp__donna__read_external", source="gmail_thread", ref="t_1"),
    )
    outcome = _extract_tier3_outcome(trace)
    assert outcome == {"action": "skip", "reason": "first decision"}


def test_normalize_send_burst_messages_handles_empty():
    assert _normalize_send_burst_messages([]) == []
    assert _normalize_send_burst_messages(None) == []


def test_normalize_send_burst_messages_passes_through_non_dict():
    """Defensive: if a message is somehow not a dict, leave it alone."""
    assert _normalize_send_burst_messages(["weird"]) == ["weird"]


def test_terminator_set_matches_phase_2a_tools():
    """Sanity: the terminator list matches the 4 ship-altering Tier 3 tools."""
    assert set(_TIER3_TERMINATORS) == {
        "skip", "kill_attention", "reshape_attention", "send_burst",
    }
