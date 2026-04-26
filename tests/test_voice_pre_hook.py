"""Tests for the PreToolUse voice_response auto-injection.

When the user explicitly asks for a voice message and the model emits a
send_burst without the voice_response marker, the PreToolUse hook rewrites
the args to inject {type: voice_response} as the first item.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from donna_runtime.hooks import _maybe_inject_voice_response


@dataclass
class _FakeTrace:
    user_message: str = ""


class MaybeInjectVoiceResponseTests(unittest.TestCase):
    def _hook_input(self, messages: list) -> dict:
        return {
            "tool_use_id": "call-123",
            "tool_name": "send_burst",
            "tool_input": {"messages": messages},
        }

    def test_injects_when_user_asked_and_no_marker_present(self) -> None:
        result = _maybe_inject_voice_response(
            self._hook_input([{"type": "text", "body": "tomorrow morning"}]),
            _FakeTrace(user_message="send me a voice message plz"),
        )
        self.assertIsNotNone(result)
        spec = result["hookSpecificOutput"]
        self.assertEqual(spec["permissionDecision"], "allow")
        new_messages = spec["updatedInput"]["messages"]
        self.assertEqual(new_messages[0], {"type": "voice_response"})
        self.assertEqual(new_messages[1]["type"], "text")

    def test_noop_when_marker_already_present(self) -> None:
        result = _maybe_inject_voice_response(
            self._hook_input([
                {"type": "voice_response"},
                {"type": "text", "body": "hi"},
            ]),
            _FakeTrace(user_message="send me a voice message"),
        )
        self.assertIsNone(result)

    def test_noop_when_user_did_not_ask_for_voice(self) -> None:
        result = _maybe_inject_voice_response(
            self._hook_input([{"type": "text", "body": "hi"}]),
            _FakeTrace(user_message="what's the weather"),
        )
        self.assertIsNone(result)

    def test_noop_when_trace_missing(self) -> None:
        result = _maybe_inject_voice_response(
            self._hook_input([{"type": "text", "body": "hi"}]),
            None,
        )
        self.assertIsNone(result)

    def test_noop_when_messages_missing(self) -> None:
        result = _maybe_inject_voice_response(
            {"tool_use_id": "x", "tool_name": "send_burst", "tool_input": {}},
            _FakeTrace(user_message="voice me"),
        )
        self.assertIsNone(result)

    def test_noop_when_messages_not_a_list(self) -> None:
        result = _maybe_inject_voice_response(
            {
                "tool_use_id": "x",
                "tool_name": "send_burst",
                "tool_input": {"messages": "not a list"},
            },
            _FakeTrace(user_message="voice me"),
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
