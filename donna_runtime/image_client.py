"""Fal.ai Flux 1.1 Pro client + Meta /media handoff.

Single public entry point `generate_and_upload`:

  composed_prompt ──► fal_client.subscribe_async (model: IMAGE_MODEL)
                        │
                        ▼
                  image URL (fal CDN)
                        │
                        ▼
                  httpx GET → bytes, mime
                        │
                        ▼
                  WhatsAppChannel.upload_media → media_id
                        │
                        ▼
                  ImageResult(media_id, fal_request_id, mime, final_prompt)

Errors are typed so the `image` tool wrapper can map each to the pre-agreed
fall-through string in the spec without catching raw Exception.

`fal_client` is imported lazily so the module (and its tests) import cleanly
even when the dep or FAL_KEY is absent — tests mock the import.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from donna_runtime.config import IMAGE_MODEL, IMAGE_SIZE

logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Base class for image-client failures the tool wrapper will translate."""


class ImageProviderError(ImageGenerationError):
    """fal.ai timeout, 5xx, transport, or missing-image-url response."""


class ImageSafetyError(ImageGenerationError):
    """fal.ai rejected the prompt via its safety filter."""


class ImageUploadError(ImageGenerationError):
    """WhatsApp /media upload failed after a successful generation."""


@dataclass(frozen=True)
class ImageResult:
    media_id: str
    fal_request_id: str
    mime_type: str
    final_prompt: str


async def generate_and_upload(
    composed_prompt: str,
    wa,  # WhatsAppChannel — untyped to avoid a circular import
    *,
    model: str = IMAGE_MODEL,
    size: str = IMAGE_SIZE,
    fal_timeout_s: float = 60.0,
    download_timeout_s: float = 20.0,
) -> ImageResult:
    """Generate one image via fal and upload to WhatsApp; return a handle."""
    if not composed_prompt or not composed_prompt.strip():
        raise ImageProviderError("empty prompt")

    payload = await _fal_subscribe(
        composed_prompt, model=model, size=size, timeout_s=fal_timeout_s
    )
    url, mime = _extract_url_and_mime(payload)
    fal_request_id = str(payload.get("request_id") or "")
    file_bytes = await _download_bytes(url, timeout_s=download_timeout_s)
    try:
        media_id = await wa.upload_media(file_bytes, mime_type=mime)
    except Exception as e:
        raise ImageUploadError(f"whatsapp /media upload failed: {e}") from e

    return ImageResult(
        media_id=media_id,
        fal_request_id=fal_request_id,
        mime_type=mime,
        final_prompt=composed_prompt,
    )


async def _fal_subscribe(
    prompt: str, *, model: str, size: str, timeout_s: float
) -> dict:
    try:
        import fal_client  # lazy: tests mock this
    except ImportError as e:
        raise ImageProviderError("fal_client not installed") from e

    arguments = {"prompt": prompt, "image_size": size}
    try:
        return await fal_client.subscribe_async(
            model, arguments=arguments, client_timeout=timeout_s
        )
    except Exception as e:
        message = str(e).lower()
        if any(t in message for t in ("safety", "content policy", "nsfw")):
            raise ImageSafetyError(f"fal safety filter: {e}") from e
        raise ImageProviderError(f"fal call failed: {e}") from e


def _extract_url_and_mime(payload: dict) -> tuple[str, str]:
    images = payload.get("images") if isinstance(payload, dict) else None
    if not images or not isinstance(images, list):
        raise ImageProviderError("fal response missing images")
    first = images[0]
    url = first.get("url") if isinstance(first, dict) else None
    if not url:
        raise ImageProviderError("fal response missing image url")
    mime = (first.get("content_type") or "image/jpeg") if isinstance(first, dict) else "image/jpeg"
    return url, mime


async def _download_bytes(url: str, *, timeout_s: float) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        raise ImageProviderError(f"download failed: {e}") from e
