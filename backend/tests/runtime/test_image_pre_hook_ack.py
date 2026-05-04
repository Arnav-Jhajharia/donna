"""Tests for the PreToolUse image ack hook.

When the model calls the `image` tool and the cap check passes, the hook
fires two side-effects on WhatsApp before fal.ai is invoked:
  - a reaction emoji on the user's inbound message (D)
  - a short "drawing this..." text bubble (A)

Both run fire-and-forget so they never block image generation. Failures
are swallowed.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from donna_runtime.hooks import (
    _IMAGE_ACK_EMOJI,
    _IMAGE_ACK_TEXT,
    _PENDING_HOOK_TASKS,
    _fire_image_ack,
)


class _FakeTrace:
    def __init__(
        self, phone: str | None, inbound_wa_message_id: str | None
    ) -> None:
        self.user_phone = phone
        self.inbound_wa_message_id = inbound_wa_message_id


async def _fire_and_drain(trace) -> None:
    """Call the hook from inside a running loop, then await any spawned tasks."""
    _fire_image_ack(trace)
    if _PENDING_HOOK_TASKS:
        await asyncio.gather(*list(_PENDING_HOOK_TASKS), return_exceptions=True)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FireImageAckTests(unittest.TestCase):
    def tearDown(self) -> None:
        _PENDING_HOOK_TASKS.clear()

    def test_noop_when_trace_missing(self) -> None:
        _run(_fire_and_drain(None))
        self.assertEqual(len(_PENDING_HOOK_TASKS), 0)

    def test_noop_when_phone_missing(self) -> None:
        _run(
            _fire_and_drain(
                _FakeTrace(phone=None, inbound_wa_message_id="wamid.x")
            )
        )
        self.assertEqual(len(_PENDING_HOOK_TASKS), 0)

    def test_fires_reaction_and_text_when_phone_present(self) -> None:
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(return_value=None)
        fake_channel.send = AsyncMock(return_value="wamid.out")

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
            "+15551234567", "wamid.in", _IMAGE_ACK_EMOJI
        )
        fake_channel.send.assert_awaited_once()
        sent_msg = fake_channel.send.await_args.args[1]
        self.assertEqual(sent_msg.body, _IMAGE_ACK_TEXT)

    def test_fires_text_even_without_inbound_message_id(self) -> None:
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(return_value=None)
        fake_channel.send = AsyncMock(return_value="wamid.out")

        with patch(
            "delivery.whatsapp.WhatsAppChannel",
            return_value=fake_channel,
        ):
            _run(
                _fire_and_drain(
                    _FakeTrace(
                        phone="+15551234567", inbound_wa_message_id=None
                    )
                )
            )

        # send_reaction is still called; the channel itself no-ops on empty id.
        fake_channel.send_reaction.assert_awaited_once_with(
            "+15551234567", None, _IMAGE_ACK_EMOJI
        )
        fake_channel.send.assert_awaited_once()

    def test_swallows_send_failures(self) -> None:
        fake_channel = AsyncMock()
        fake_channel.send_reaction = AsyncMock(side_effect=RuntimeError("boom"))
        fake_channel.send = AsyncMock(side_effect=RuntimeError("boom"))

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
        fake_channel.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
