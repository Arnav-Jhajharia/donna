"""Tests for the Deepgram STT client.

Covers:
- happy path: parses transcript out of standard Deepgram listen response
- empty audio bytes returns ""
- missing API key returns ""
- HTTP error returns ""
- malformed response shape returns ""
- response parsing helper handles edge cases
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from ingress import stt


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _mock_response(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "" if json_body is None else "<body>"
    resp.json = MagicMock(return_value=json_body or {})
    return resp


class ExtractTranscriptTests(unittest.TestCase):
    def test_pulls_first_alternative(self) -> None:
        body = {
            "results": {
                "channels": [
                    {"alternatives": [{"transcript": "tomorrow morning, 8am"}]},
                ],
            },
        }
        self.assertEqual(stt._extract_transcript(body), "tomorrow morning, 8am")

    def test_strips_whitespace(self) -> None:
        body = {
            "results": {
                "channels": [{"alternatives": [{"transcript": "  hi there  "}]}]
            }
        }
        self.assertEqual(stt._extract_transcript(body), "hi there")

    def test_empty_when_no_channels(self) -> None:
        self.assertEqual(stt._extract_transcript({"results": {"channels": []}}), "")

    def test_empty_when_no_alternatives(self) -> None:
        body = {"results": {"channels": [{"alternatives": []}]}}
        self.assertEqual(stt._extract_transcript(body), "")

    def test_empty_on_missing_keys(self) -> None:
        self.assertEqual(stt._extract_transcript({}), "")
        self.assertEqual(stt._extract_transcript({"results": {}}), "")

    def test_empty_on_garbage_shape(self) -> None:
        self.assertEqual(stt._extract_transcript({"results": "nope"}), "")
        self.assertEqual(stt._extract_transcript({"results": {"channels": "nope"}}), "")


class TranscribeVoiceTests(unittest.TestCase):
    def test_empty_bytes_returns_empty_string(self) -> None:
        result = _run(stt.transcribe_voice(b"", "audio/ogg"))
        self.assertEqual(result, "")

    def test_missing_api_key_returns_empty_string(self) -> None:
        with patch.object(stt.settings, "deepgram_api_key", ""):
            result = _run(stt.transcribe_voice(b"\x00\x01\x02", "audio/ogg"))
        self.assertEqual(result, "")

    def test_happy_path(self) -> None:
        body = {
            "results": {
                "channels": [{"alternatives": [{"transcript": "hey donna"}]}]
            }
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=_mock_response(200, body))

        with patch.object(stt.settings, "deepgram_api_key", "sk-test"), \
             patch.object(stt.settings, "deepgram_model", "nova-3"), \
             patch.object(stt.httpx, "AsyncClient", return_value=mock_client):
            result = _run(stt.transcribe_voice(b"oggbytes", "audio/ogg"))

        self.assertEqual(result, "hey donna")
        mock_client.post.assert_awaited_once()
        # Verify Authorization header was set
        _args, kwargs = mock_client.post.await_args
        headers = kwargs.get("headers") or {}
        self.assertTrue(
            any("Token sk-test" in str(v) for v in headers.values()),
            f"expected Authorization header, got {headers!r}",
        )
        # Verify content-type passed through
        self.assertEqual(headers.get("Content-Type"), "audio/ogg")

    def test_http_error_returns_empty_string(self) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=_mock_response(500, {}))

        with patch.object(stt.settings, "deepgram_api_key", "sk-test"), \
             patch.object(stt.httpx, "AsyncClient", return_value=mock_client):
            result = _run(stt.transcribe_voice(b"oggbytes", "audio/ogg"))

        self.assertEqual(result, "")

    def test_network_error_returns_empty_string(self) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))

        with patch.object(stt.settings, "deepgram_api_key", "sk-test"), \
             patch.object(stt.httpx, "AsyncClient", return_value=mock_client):
            result = _run(stt.transcribe_voice(b"oggbytes", "audio/ogg"))

        self.assertEqual(result, "")

    def test_malformed_response_returns_empty_string(self) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=_mock_response(200, {"unexpected": "shape"}))

        with patch.object(stt.settings, "deepgram_api_key", "sk-test"), \
             patch.object(stt.httpx, "AsyncClient", return_value=mock_client):
            result = _run(stt.transcribe_voice(b"oggbytes", "audio/ogg"))

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
