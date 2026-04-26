"""Tests for the deterministic voice-request detector.

The detector decides whether to inject a hard 'use voice_response' directive
into the per-turn runtime context. False positives are ok-ish (extra context
line), false negatives are the failure mode that put us here in the first
place.
"""
from __future__ import annotations

import unittest

from donna_runtime.context_builder import _detect_voice_request


class DetectVoiceRequestTests(unittest.TestCase):
    def test_explicit_phrasings_trigger(self) -> None:
        for text in [
            "send me a voice message",
            "send me a vm",
            "send me a vm rn",
            "voice me",
            "voice it",
            "can you voice that?",
            "say it out loud",
            "talk to me",
            "send a voice note please",
            "send me an audio message",
            "reply in audio",
        ]:
            with self.subTest(text=text):
                self.assertTrue(
                    _detect_voice_request({"raw_input": text}),
                    f"expected detector to fire on {text!r}",
                )

    def test_case_insensitive(self) -> None:
        self.assertTrue(_detect_voice_request({"raw_input": "Voice ME now please"}))

    def test_does_not_trigger_on_unrelated_text(self) -> None:
        for text in [
            "hi donna",
            "what's the time",
            "remind me to call sarah at 6pm",
            "i sent a text earlier, did you get it",
            "i don't want to talk",
        ]:
            with self.subTest(text=text):
                self.assertFalse(
                    _detect_voice_request({"raw_input": text}),
                    f"expected detector to stay quiet on {text!r}",
                )

    def test_empty_input(self) -> None:
        self.assertFalse(_detect_voice_request({}))
        self.assertFalse(_detect_voice_request({"raw_input": ""}))
        self.assertFalse(_detect_voice_request({"raw_input": None}))


if __name__ == "__main__":
    unittest.main()
