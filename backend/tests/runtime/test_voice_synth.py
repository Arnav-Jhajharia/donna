"""Tests for the voice synthesis hook.

Covers:
- marker detection and burst replacement on success
- silent fallback to text on TTS failure
- silent fallback when DONNA_VOICE_ENABLED=false
- empty-text and over-cap guards
- buffer left untouched when no marker is present
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from delivery.messages import (
    AudioMessage,
    Delay,
    TextMessage,
    VoiceResponseMarker,
)
from donna_runtime import voice_synth
from donna_runtime.hooks import _OUTBOUND_BUFFER


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class _BufferContext:
    """Tiny helper: set the OUTBOUND_BUFFER ContextVar inside the test."""

    def __init__(self, items: list) -> None:
        self.items = items
        self._token = None

    def __enter__(self) -> list:
        self._token = _OUTBOUND_BUFFER.set(self.items)
        return self.items

    def __exit__(self, *exc) -> None:
        _OUTBOUND_BUFFER.reset(self._token)


class CollectTextTests(unittest.TestCase):
    def test_joins_text_bodies_skipping_markers_and_delays(self) -> None:
        buffer = [
            VoiceResponseMarker(),
            TextMessage(body="hey"),
            Delay(seconds=1.0),
            TextMessage(body="tomorrow morning"),
        ]
        self.assertEqual(voice_synth._collect_text(buffer), "hey tomorrow morning")

    def test_empty_when_no_text(self) -> None:
        buffer = [VoiceResponseMarker(), Delay(seconds=1.0)]
        self.assertEqual(voice_synth._collect_text(buffer), "")


class StripMarkerTests(unittest.TestCase):
    def test_strips_only_markers(self) -> None:
        buffer = [
            VoiceResponseMarker(),
            TextMessage(body="hi"),
            VoiceResponseMarker(),
            Delay(seconds=0.5),
        ]
        voice_synth._strip_marker(buffer)
        self.assertEqual(len(buffer), 2)
        self.assertIsInstance(buffer[0], TextMessage)
        self.assertIsInstance(buffer[1], Delay)


class ReplaceWithAudioTests(unittest.TestCase):
    def test_clears_text_keeps_delays_appends_audio(self) -> None:
        buffer = [
            VoiceResponseMarker(),
            Delay(seconds=1.0),
            TextMessage(body="hi"),
        ]
        audio = AudioMessage(media_id="abc123", voice=True)
        voice_synth._replace_with_audio(buffer, audio)
        # Delay preserved + audio appended; text dropped (now in audio).
        self.assertEqual(len(buffer), 2)
        self.assertIsInstance(buffer[0], Delay)
        self.assertIs(buffer[1], audio)


class MaybeSynthesizeVoiceTests(unittest.TestCase):
    def test_noop_when_no_marker(self) -> None:
        buffer = [TextMessage(body="hi")]
        with _BufferContext(buffer):
            _run(voice_synth.maybe_synthesize_voice())
        self.assertEqual(buffer, [TextMessage(body="hi")])

    def test_noop_when_buffer_unset(self) -> None:
        # ContextVar default is None — should silently no-op.
        _run(voice_synth.maybe_synthesize_voice())  # must not raise

    def test_strips_marker_when_voice_disabled(self) -> None:
        buffer = [VoiceResponseMarker(), TextMessage(body="hi")]
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", False):
            _run(voice_synth.maybe_synthesize_voice())
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)

    def test_strips_marker_when_text_empty(self) -> None:
        buffer = [VoiceResponseMarker()]
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", True):
            _run(voice_synth.maybe_synthesize_voice())
        self.assertEqual(buffer, [])

    def test_strips_marker_when_over_char_cap(self) -> None:
        buffer = [VoiceResponseMarker(), TextMessage(body="x" * 700)]
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", True), \
             patch.object(voice_synth.settings, "donna_voice_max_chars", 600):
            _run(voice_synth.maybe_synthesize_voice())
        # Text preserved, marker stripped
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)

    def test_replaces_burst_on_successful_synthesis(self) -> None:
        buffer = [VoiceResponseMarker(), TextMessage(body="tomorrow morning, 8am")]
        fake_channel = AsyncMock()
        fake_channel.upload_media = AsyncMock(return_value="media_xyz")
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", True), \
             patch.object(voice_synth.settings, "donna_voice_max_chars", 600), \
             patch.object(voice_synth, "synthesize_tts",
                          AsyncMock(return_value=b"\x00\x01ogg-bytes")):
            _run(voice_synth.maybe_synthesize_voice(channel=fake_channel))
        self.assertEqual(len(buffer), 1)
        audio = buffer[0]
        self.assertIsInstance(audio, AudioMessage)
        self.assertEqual(audio.media_id, "media_xyz")
        self.assertTrue(audio.voice)
        fake_channel.upload_media.assert_awaited_once()
        # MIME must be the WA native voice-note shape
        args, kwargs = fake_channel.upload_media.await_args
        self.assertIn("ogg", (args[1] if len(args) > 1 else kwargs.get("mime_type", "")))

    def test_falls_back_to_text_on_tts_failure(self) -> None:
        buffer = [VoiceResponseMarker(), TextMessage(body="hi")]
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", True), \
             patch.object(voice_synth.settings, "donna_voice_max_chars", 600), \
             patch.object(voice_synth, "synthesize_tts",
                          AsyncMock(side_effect=RuntimeError("tts boom"))):
            _run(voice_synth.maybe_synthesize_voice(channel=AsyncMock()))
        # Marker stripped, text preserved
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)
        self.assertEqual(buffer[0].body, "hi")

    def test_forces_voice_when_user_asked_even_without_marker(self) -> None:
        from dataclasses import dataclass

        @dataclass
        class _FakeTrace:
            user_message: str = "send a voice message plz"

        buffer = [TextMessage(body="here you go arnav")]
        fake_channel = AsyncMock()
        fake_channel.upload_media = AsyncMock(return_value="media_forced")
        token = voice_synth._CURRENT_TRACE.set(_FakeTrace())
        try:
            with _BufferContext(buffer), \
                 patch.object(voice_synth.settings, "donna_voice_enabled", True), \
                 patch.object(voice_synth.settings, "donna_voice_max_chars", 600), \
                 patch.object(voice_synth, "synthesize_tts",
                              AsyncMock(return_value=b"oggbytes")):
                _run(voice_synth.maybe_synthesize_voice(channel=fake_channel))
        finally:
            voice_synth._CURRENT_TRACE.reset(token)

        # Forced path: text replaced with audio even though model never emitted marker
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], AudioMessage)
        self.assertEqual(buffer[0].media_id, "media_forced")
        self.assertTrue(buffer[0].voice)

    def test_does_not_force_voice_when_no_voice_request(self) -> None:
        from dataclasses import dataclass

        @dataclass
        class _FakeTrace:
            user_message: str = "what's the weather"

        buffer = [TextMessage(body="sunny")]
        fake_channel = AsyncMock()
        token = voice_synth._CURRENT_TRACE.set(_FakeTrace())
        try:
            with _BufferContext(buffer), \
                 patch.object(voice_synth.settings, "donna_voice_enabled", True):
                _run(voice_synth.maybe_synthesize_voice(channel=fake_channel))
        finally:
            voice_synth._CURRENT_TRACE.reset(token)

        # Untouched
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)
        fake_channel.upload_media.assert_not_called()

    def test_falls_back_to_text_on_upload_failure(self) -> None:
        buffer = [VoiceResponseMarker(), TextMessage(body="hi")]
        fake_channel = AsyncMock()
        fake_channel.upload_media = AsyncMock(side_effect=RuntimeError("upload boom"))
        with _BufferContext(buffer), \
             patch.object(voice_synth.settings, "donna_voice_enabled", True), \
             patch.object(voice_synth.settings, "donna_voice_max_chars", 600), \
             patch.object(voice_synth, "synthesize_tts",
                          AsyncMock(return_value=b"oggbytes")):
            _run(voice_synth.maybe_synthesize_voice(channel=fake_channel))
        self.assertEqual(len(buffer), 1)
        self.assertIsInstance(buffer[0], TextMessage)


if __name__ == "__main__":
    unittest.main()
