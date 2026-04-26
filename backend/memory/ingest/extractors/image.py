"""Image extractor: caption + OCR via Claude Haiku vision.

One round-trip produces a structured caption and any visible text. We
use Haiku 4.5 (already wired via ``AsyncAnthropic`` elsewhere) — vision
is included at the standard tier and the per-image cost is well under
a cent.
"""
from __future__ import annotations

import asyncio
import base64
import logging

from backend.config import get_settings

from . import ExtractedDocument

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 600
_TIMEOUT_S = 25.0
_VISION_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")

_PROMPT = """You are Donna's image-ingest helper. Read this image the user just sent her and return a tight description plus any visible text.

Output exactly two sections, in this order, separated by a blank line:

CAPTION
A two to four sentence read of what's in the image, in lowercase. What the user is showing. Concrete. No filler. If a person is visible, describe pose and context, not identity. If it's a screenshot, name the app or context.

VISIBLE TEXT
Every legible word/phrase on the image, line by line. Preserve order. If there is no readable text, write `(none)`.

No prose around the sections. No headers other than the two above."""


async def extract(
    file_bytes: bytes, *, mime_type: str, filename: str
) -> ExtractedDocument | None:
    if not file_bytes:
        return None
    media_type = (mime_type or "image/jpeg").lower()
    if media_type not in _VISION_MIMES:
        # Best-effort: WhatsApp images sometimes arrive with weird mimes
        # (e.g. application/octet-stream). Default to jpeg.
        media_type = "image/jpeg"

    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.info("image extract: no anthropic key — skipping caption")
        return None

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        logger.warning("anthropic SDK missing — image extract returns None")
        return None

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    encoded = base64.standard_b64encode(file_bytes).decode("ascii")

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": encoded,
                                },
                            },
                            {"type": "text", "text": _PROMPT},
                        ],
                    }
                ],
            ),
            timeout=_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning("image extract: timeout for %s", filename or "<unnamed>")
        return None
    except Exception:
        logger.exception("image extract: vision call failed")
        return None

    raw = ""
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            raw += getattr(block, "text", "") or ""
    raw = raw.strip()
    if not raw:
        return None

    caption, visible_text = _split_sections(raw)
    body_parts: list[str] = []
    if caption:
        body_parts.append(caption)
    if visible_text and visible_text.lower() != "(none)":
        body_parts.append("Visible text:\n" + visible_text)
    body = "\n\n".join(body_parts).strip()
    if not body:
        return None

    title_seed = (filename or "image").rsplit(".", 1)[0]
    return ExtractedDocument(
        text=body,
        title=title_seed,
        page_count=1,
        extra_metadata={"format": "image", "media_type": media_type},
    )


def _split_sections(raw: str) -> tuple[str, str]:
    """Pull the CAPTION and VISIBLE TEXT sections out of the model output.

    Tolerant of small format drift — falls back to ``(raw, "")`` if the
    expected headers are missing so we still get a usable caption.
    """
    upper = raw.upper()
    cap_idx = upper.find("CAPTION")
    vt_idx = upper.find("VISIBLE TEXT")

    if cap_idx == -1:
        return raw.strip(), ""

    caption_start = cap_idx + len("CAPTION")
    if vt_idx != -1 and vt_idx > cap_idx:
        caption = raw[caption_start:vt_idx].strip()
        visible = raw[vt_idx + len("VISIBLE TEXT") :].strip()
    else:
        caption = raw[caption_start:].strip()
        visible = ""

    caption = caption.lstrip(":-\n ").strip()
    visible = visible.lstrip(":-\n ").strip()
    return caption, visible
