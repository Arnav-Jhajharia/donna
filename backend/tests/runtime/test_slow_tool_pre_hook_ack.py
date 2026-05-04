"""Tests for the PreToolUse slow-tool ack hook.

When the model calls a known-slow tool (recall, research, agentic
web search, composio meta tools, etc.) the hook fires a reaction emoji
on the user's inbound WhatsApp message so the user feels acknowledged
without Donna saying "let me check" — that violates the prompt rule
against announcing tool calls.

Idempotent within a turn: only the first slow-tool call fires the
reaction. Subsequent calls in the same turn are silent. Across turns
the ContextVar is reset by ``trace_hook_context``.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from donna_runtime.hooks import (
    _PENDING_HOOK_TASKS,
    _SLOW_ACK_FIRED,
    _SLOW_TOOL_ACK_EMOJI,
    _fire_slow_tool_ack,
)


class _FakeTrace:
    def __init__(self, phone, inbound_wa_message_id):
        self.user_phone = phone
        self.inbound_wa_message_id = inbound_wa_message_id


async def _fire_and_drain(trace) -> None:
    _fire_slow_tool_ack(trace)
    if _PENDING_HOOK_TASKS:
        await asyncio.gather(*list(_PENDING_HOOK_TASKS), return_exceptions=True)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FireSlowToolAckTests(unittest.TestCase):
    def setUp(self) -> None:
        # Force a clean ContextVar state per test. The default is False.
        try:
            _SLOW_ACK_FIRED.set(False)
        except LookupError:
            pass

    def tearDown(self) -> None:
        _PENDING_HOOK_TASKS.clear()

    def test_noop_when_trace_missing(self) -> None:
        _run(_fire_and_drain(None))
        self.assertEqual(len(_PENDING_HOOK_TASKS), 0)

    def test_noop_when_phone_or_inbound_id_missing(self) -> None:
        _run(_fire_and_drain(_FakeTrace(phone=None, inbound_wa_message_id="wamid.x")))
        _run(_fire_and_drain(_FakeTrace(phone="+1", inbound_wa_message_id=None)))
        self.assertEqual(len(_PENDING_HOOK_TASKS), 0)

    def test_fires_reaction_when_phone_and_id_present(self) -> None:
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(return_value=None)

        with patch(
            "delivery.whatsapp.WhatsAppChannel",
            return_value=fake_channel,
        ):
            _run(
                _fire_and_drain(
                    _FakeTrace(
                        phone="+15551234567", inbound_wa_message_id="wamid.in"
                    )
                )
            )

        fake_channel.send_reaction.assert_awaited_once_with(
            "+15551234567", "wamid.in", _SLOW_TOOL_ACK_EMOJI
        )

    def test_idempotent_within_a_turn(self) -> None:
        """Two slow-tool calls in the same turn should produce ONE reaction."""
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(return_value=None)

        async def _double_fire():
            trace = _FakeTrace(
                phone="+15551234567", inbound_wa_message_id="wamid.in"
            )
            _fire_slow_tool_ack(trace)
            _fire_slow_tool_ack(trace)
            if _PENDING_HOOK_TASKS:
                await asyncio.gather(
                    *list(_PENDING_HOOK_TASKS), return_exceptions=True
                )

        with patch(
            "delivery.whatsapp.WhatsAppChannel",
            return_value=fake_channel,
        ):
            _run(_double_fire())

        fake_channel.send_reaction.assert_awaited_once()

    def test_swallows_send_failures(self) -> None:
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "delivery.whatsapp.WhatsAppChannel",
            return_value=fake_channel,
        ):
            _run(
                _fire_and_drain(
                    _FakeTrace(
                        phone="+15551234567", inbound_wa_message_id="wamid.in"
                    )
                )
            )

        fake_channel.send_reaction.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
