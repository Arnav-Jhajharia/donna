"""fal.ai client for the Day 1 dashboard illustration.

Different from ``donna_runtime.image_client`` — that one generates and uploads
to WhatsApp /media. This one returns the bare CDN URL so the dashboard can
serve / cache / proxy it however it wants.

``fal_client`` is imported lazily so the module loads on machines without the
SDK or without ``FAL_KEY`` set — tests mock the import.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.illustration.prompt import (
    DEFAULT_IMAGE_SIZE,
    DEFAULT_STYLE,
    FalArguments,
    IllustrationRequest,
    build_arguments,
)

logger = logging.getLogger(__name__)

# Recraft v3 — strong illustration consistency, has style presets we use to
# keep the look uniform across cities and times. Returns raster (PNG/JPEG).
FAL_MODEL = "fal-ai/recraft-v3"
DEFAULT_TIMEOUT_S = 60.0


class IllustrationError(Exception):
    """Base class for illustration failures."""


class IllustrationProviderError(IllustrationError):
    """fal.ai timeout, transport, or missing-image-url response."""


class IllustrationSafetyError(IllustrationError):
    """fal.ai safety filter rejected the prompt."""


@dataclass(frozen=True)
class IllustrationResult:
    """One generated illustration."""

    url: str
    mime_type: str
    fal_request_id: str
    arguments: FalArguments
    request: IllustrationRequest


async def generate(
    request: IllustrationRequest,
    *,
    model: str = FAL_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> IllustrationResult:
    """Generate one illustration. Returns a typed result with the CDN URL."""
    args = build_arguments(request)
    payload = await _fal_subscribe(args, model=model, timeout_s=timeout_s)
    url, mime = _extract_url_and_mime(payload)
    return IllustrationResult(
        url=url,
        mime_type=mime,
        fal_request_id=str(payload.get("request_id") or ""),
        arguments=args,
        request=request,
    )


async def _fal_subscribe(
    args: FalArguments, *, model: str, timeout_s: float
) -> dict:
    try:
        import fal_client  # lazy: tests mock this
    except ImportError as exc:
        raise IllustrationProviderError("fal_client not installed") from exc

    try:
        return await fal_client.subscribe_async(
            model, arguments=args.to_dict(), client_timeout=timeout_s
        )
    except Exception as exc:  # noqa: BLE001 — boundary translation
        message = str(exc).lower()
        if any(t in message for t in ("safety", "content policy", "nsfw")):
            raise IllustrationSafetyError(f"fal safety filter: {exc}") from exc
        raise IllustrationProviderError(f"fal call failed: {exc}") from exc


def _extract_url_and_mime(payload: dict) -> tuple[str, str]:
    images = payload.get("images") if isinstance(payload, dict) else None
    if not images or not isinstance(images, list):
        raise IllustrationProviderError("fal response missing images")
    first = images[0]
    if not isinstance(first, dict):
        raise IllustrationProviderError("fal response image entry malformed")
    url = first.get("url")
    if not url:
        raise IllustrationProviderError("fal response missing image url")
    mime = first.get("content_type") or "image/png"
    return str(url), str(mime)


__all__ = [
    "DEFAULT_IMAGE_SIZE",
    "DEFAULT_STYLE",
    "FAL_MODEL",
    "IllustrationError",
    "IllustrationProviderError",
    "IllustrationResult",
    "IllustrationSafetyError",
    "generate",
]
