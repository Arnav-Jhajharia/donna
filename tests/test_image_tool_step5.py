"""Step 5 tests: image_client.generate_and_upload.

Both external surfaces are mocked:

  - fal_client.subscribe_async (inserted into sys.modules before import)
  - httpx.AsyncClient (for the CDN download)
  - WhatsAppChannel.upload_media (a bare AsyncMock passed in)

The tool wrapper (step 7) will translate the typed exceptions raised here
into the pre-agreed fall-through strings from the spec.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from donna_runtime import image_client
from donna_runtime.image_client import (
    ImageProviderError,
    ImageResult,
    ImageSafetyError,
    ImageUploadError,
    _extract_url_and_mime,
    generate_and_upload,
)


FAL_OK_PAYLOAD = {
    "request_id": "fal_req_abc",
    "images": [
        {
            "url": "https://fal.cdn/abc.jpg",
            "content_type": "image/jpeg",
            "width": 1024,
            "height": 1024,
        }
    ],
}


def _install_fal_stub(subscribe_async: AsyncMock) -> types.ModuleType:
    """Register a fake `fal_client` module so `import fal_client` inside
    `_fal_subscribe` resolves to our mock. Caller is responsible for cleanup.
    """
    mod = types.ModuleType("fal_client")
    mod.subscribe_async = subscribe_async  # type: ignore[attr-defined]
    sys.modules["fal_client"] = mod
    return mod


def _uninstall_fal_stub() -> None:
    sys.modules.pop("fal_client", None)


@pytest.fixture
def fal_ok():
    subscribe = AsyncMock(return_value=FAL_OK_PAYLOAD)
    _install_fal_stub(subscribe)
    yield subscribe
    _uninstall_fal_stub()


@pytest.fixture
def wa_mock():
    wa = MagicMock()
    wa.upload_media = AsyncMock(return_value="wa_media_42")
    return wa


def _httpx_cm(status: int = 200, body: bytes = b"\x89PNG\r\nstub") -> tuple:
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status), request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    client_instance = MagicMock()
    client_instance.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_instance)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, client_instance


class TestExtractUrlAndMime:
    def test_happy_path(self) -> None:
        url, mime = _extract_url_and_mime(FAL_OK_PAYLOAD)
        assert url == "https://fal.cdn/abc.jpg"
        assert mime == "image/jpeg"

    def test_default_mime_when_missing(self) -> None:
        payload = {"images": [{"url": "https://x/y.png"}]}
        _, mime = _extract_url_and_mime(payload)
        assert mime == "image/jpeg"  # documented default

    def test_missing_images_raises(self) -> None:
        with pytest.raises(ImageProviderError):
            _extract_url_and_mime({})

    def test_empty_images_list_raises(self) -> None:
        with pytest.raises(ImageProviderError):
            _extract_url_and_mime({"images": []})

    def test_missing_url_raises(self) -> None:
        with pytest.raises(ImageProviderError):
            _extract_url_and_mime({"images": [{"content_type": "image/png"}]})


class TestGenerateAndUploadHappy:
    def test_returns_image_result_with_media_id(self, fal_ok, wa_mock) -> None:
        cm, _ = _httpx_cm(body=b"\x89PNG\r\nstub")
        with patch("httpx.AsyncClient", return_value=cm):
            result = asyncio.run(generate_and_upload("warm hearth, eleven days", wa_mock))

        assert isinstance(result, ImageResult)
        assert result.media_id == "wa_media_42"
        assert result.fal_request_id == "fal_req_abc"
        assert result.mime_type == "image/jpeg"
        assert result.final_prompt == "warm hearth, eleven days"

    def test_passes_prompt_and_image_size_to_fal(self, fal_ok, wa_mock) -> None:
        cm, _ = _httpx_cm()
        with patch("httpx.AsyncClient", return_value=cm):
            asyncio.run(generate_and_upload("loop closed", wa_mock))

        args, kwargs = fal_ok.call_args
        assert args[0] == "fal-ai/flux-pro/v1.1"
        assert kwargs["arguments"]["prompt"] == "loop closed"
        assert kwargs["arguments"]["image_size"] == "square_hd"

    def test_uploads_bytes_with_mime(self, fal_ok, wa_mock) -> None:
        cm, _ = _httpx_cm(body=b"PNGBYTES")
        with patch("httpx.AsyncClient", return_value=cm):
            asyncio.run(generate_and_upload("x", wa_mock))

        args, kwargs = wa_mock.upload_media.call_args
        assert args[0] == b"PNGBYTES"
        assert kwargs["mime_type"] == "image/jpeg"


class TestGenerateAndUploadFailures:
    def test_empty_prompt_raises_provider(self, wa_mock) -> None:
        with pytest.raises(ImageProviderError, match="empty prompt"):
            asyncio.run(generate_and_upload("   ", wa_mock))

    def test_fal_safety_error_is_typed(self, wa_mock) -> None:
        subscribe = AsyncMock(side_effect=RuntimeError("request failed: safety filter hit"))
        _install_fal_stub(subscribe)
        try:
            with pytest.raises(ImageSafetyError):
                asyncio.run(generate_and_upload("x", wa_mock))
        finally:
            _uninstall_fal_stub()

    def test_fal_timeout_is_provider_error(self, wa_mock) -> None:
        subscribe = AsyncMock(side_effect=TimeoutError("fal timed out"))
        _install_fal_stub(subscribe)
        try:
            with pytest.raises(ImageProviderError):
                asyncio.run(generate_and_upload("x", wa_mock))
        finally:
            _uninstall_fal_stub()

    def test_missing_fal_client_module(self, wa_mock) -> None:
        # Ensure no stub is installed.
        _uninstall_fal_stub()
        with patch.dict(sys.modules, {"fal_client": None}):
            with pytest.raises(ImageProviderError, match="fal_client not installed"):
                asyncio.run(generate_and_upload("x", wa_mock))

    def test_download_4xx_is_provider_error(self, fal_ok, wa_mock) -> None:
        cm, _ = _httpx_cm(status=500)
        with patch("httpx.AsyncClient", return_value=cm):
            with pytest.raises(ImageProviderError, match="download failed"):
                asyncio.run(generate_and_upload("x", wa_mock))
        # upload_media should never fire if download failed
        wa_mock.upload_media.assert_not_called()

    def test_upload_failure_is_typed(self, fal_ok, wa_mock) -> None:
        wa_mock.upload_media = AsyncMock(side_effect=RuntimeError("meta 413"))
        cm, _ = _httpx_cm()
        with patch("httpx.AsyncClient", return_value=cm):
            with pytest.raises(ImageUploadError, match="whatsapp /media upload failed"):
                asyncio.run(generate_and_upload("x", wa_mock))
