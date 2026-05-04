"""Step 3 tests: WhatsAppChannel.upload_media posts bytes to /media and returns the id.

Mocks httpx to avoid hitting the real Meta API.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture
def wa_channel(monkeypatch):
    # `delivery.whatsapp` reads the module-level `settings` object, which is
    # instantiated once at import. Patch the live attributes so the fixture
    # works regardless of prior imports.
    from config import settings
    from delivery.whatsapp import WhatsAppChannel
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "test_phone_id")
    monkeypatch.setattr(settings, "whatsapp_token", "test_token")
    return WhatsAppChannel()


def _make_client_cm(response: MagicMock):
    """Build a context-manager httpx.AsyncClient mock whose `post` returns `response`."""
    client_instance = MagicMock()
    client_instance.post = AsyncMock(return_value=response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_instance)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, client_instance


class TestUploadMedia:
    def test_media_url_shape(self, wa_channel) -> None:
        assert wa_channel._media_url.endswith("/test_phone_id/media")
        assert wa_channel._media_url.startswith("https://graph.facebook.com/")

    def test_upload_returns_id_from_meta(self, wa_channel) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": "wa_media_999"}
        cm, client = _make_client_cm(resp)

        with patch("httpx.AsyncClient", return_value=cm):
            media_id = asyncio.run(
                wa_channel.upload_media(b"\x89PNG\r\n...", "image/png")
            )

        assert media_id == "wa_media_999"
        # Verify the right URL + auth header + multipart shape
        args, kwargs = client.post.call_args
        assert args[0].endswith("/test_phone_id/media")
        assert kwargs["headers"] == {"Authorization": "Bearer test_token"}
        assert kwargs["data"] == {
            "messaging_product": "whatsapp",
            "type": "image/png",
        }
        assert "file" in kwargs["files"]
        filename, content, mime = kwargs["files"]["file"]
        assert content == b"\x89PNG\r\n..."
        assert mime == "image/png"

    def test_default_mime_is_png(self, wa_channel) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": "wa_123"}
        cm, client = _make_client_cm(resp)

        with patch("httpx.AsyncClient", return_value=cm):
            asyncio.run(wa_channel.upload_media(b"bytes"))

        _, kwargs = client.post.call_args
        assert kwargs["data"]["type"] == "image/png"
        assert kwargs["files"]["file"][2] == "image/png"

    def test_4xx_response_raises(self, wa_channel) -> None:
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "bad request"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=resp
        )
        cm, _ = _make_client_cm(resp)

        with patch("httpx.AsyncClient", return_value=cm):
            with pytest.raises(httpx.HTTPStatusError):
                asyncio.run(wa_channel.upload_media(b"bytes"))

    def test_missing_id_in_response_raises(self, wa_channel) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"something_else": "oops"}
        cm, _ = _make_client_cm(resp)

        with patch("httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="missing id"):
                asyncio.run(wa_channel.upload_media(b"bytes"))
