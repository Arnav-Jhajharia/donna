from __future__ import annotations

import asyncio
import unittest

from donna_runtime import tool_logic
from donna_runtime.tool_logic import send_burst_result, set_voice_filter_enabled
from donna_runtime.voice_filter import filter_burst_items, filter_text


class FilterTextTests(unittest.TestCase):
    def test_clean_text_has_no_violations(self) -> None:
        res = filter_text("ok, ping me in an hour")
        self.assertTrue(res.clean)
        self.assertEqual(res.text, "ok, ping me in an hour")

    def test_strips_em_dash(self) -> None:
        res = filter_text("sure — i'll handle it")
        self.assertIn("em_dash", res.violations)
        self.assertNotIn("—", res.text)
        self.assertEqual(res.text, "sure, i'll handle it")

    def test_strips_semicolon(self) -> None:
        res = filter_text("done; moving on")
        self.assertIn("semicolon", res.violations)
        self.assertNotIn(";", res.text)

    def test_strips_banned_phrase(self) -> None:
        res = filter_text("I understand, you want coffee")
        self.assertTrue(any(v.startswith("banned_phrase") for v in res.violations))
        self.assertNotIn("I understand", res.text)

    def test_lowercases_sentence_starts(self) -> None:
        res = filter_text("Ok. Done.")
        self.assertIn("uppercase_sentence_start", res.violations)
        self.assertEqual(res.text, "ok. done.")

    def test_idempotent(self) -> None:
        once = filter_text("Sure — I understand; done.").text
        twice = filter_text(once).text
        self.assertEqual(once, twice)

    def test_empty_is_clean(self) -> None:
        self.assertEqual(filter_text("").text, "")
        self.assertEqual(filter_text("").violations, ())


class FilterBurstItemsTests(unittest.TestCase):
    def test_string_items(self) -> None:
        out, vios = filter_burst_items(["ok — sure", "fine"])
        self.assertEqual(out[0], "ok, sure")
        self.assertEqual(out[1], "fine")
        self.assertIn("em_dash", vios)

    def test_dict_body_filtered(self) -> None:
        out, vios = filter_burst_items([{"type": "text", "body": "done; next"}])
        self.assertEqual(out[0]["body"], "done. next")
        self.assertIn("semicolon", vios)

    def test_delay_passes_through(self) -> None:
        out, vios = filter_burst_items([{"type": "delay", "seconds": 1.0}])
        self.assertEqual(out[0], {"type": "delay", "seconds": 1.0})
        self.assertEqual(vios, ())


class SendBurstIntegrationTests(unittest.TestCase):
    def test_send_burst_applies_filter_when_enabled(self) -> None:
        set_voice_filter_enabled(True)
        token = tool_logic._OUTBOUND_BUFFER.set([])
        try:
            result = asyncio.run(
                send_burst_result({"messages": [{"type": "text", "body": "ok — sure"}]})
            )
            buffer = tool_logic._OUTBOUND_BUFFER.get()
            self.assertEqual(len(buffer), 1)
            self.assertEqual(buffer[0].body, "ok, sure")
            self.assertIn("Sent 1 messages", result["content"][0]["text"])
        finally:
            tool_logic._OUTBOUND_BUFFER.reset(token)

    def test_send_burst_skips_filter_when_disabled(self) -> None:
        set_voice_filter_enabled(False)
        token = tool_logic._OUTBOUND_BUFFER.set([])
        try:
            asyncio.run(
                send_burst_result({"messages": [{"type": "text", "body": "ok — sure"}]})
            )
            buffer = tool_logic._OUTBOUND_BUFFER.get()
            self.assertEqual(buffer[0].body, "ok — sure")
        finally:
            set_voice_filter_enabled(True)
            tool_logic._OUTBOUND_BUFFER.reset(token)


if __name__ == "__main__":
    unittest.main()
