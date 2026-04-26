"""Deepgram speech-to-text for inbound voice notes.

The ingress pipeline calls `transcribe_voice` when an inbound payload carries
voice bytes. The returned transcript replaces the empty text body, so the
brain runs a normal text turn — only the per-turn `_inbound_modality` flag
tells Donna the message arrived as voice.

Failure mode: empty string back. Caller is expected to handle that (the
ingress layer keeps the placeholder so Donna can ask the user to text instead).
"""
from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_TRANSCRIBE_TIMEOUT_S = 12.0


async def transcribe_voice(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
) -> str:
    """POST audio bytes to Deepgram, return the best-channel transcript.

    Returns an empty string on any failure. Never raises — STT errors must
    not break the ingress pipeline.
    """
    if not audio_bytes:
        return ""
    if not settings.deepgram_api_key:
        logger.warning("deepgram_api_key not configured — skipping transcription")
        return ""

    params = {
        "model": settings.deepgram_model,
        "smart_format": "true",
        "punctuate": "true",
        "detect_language": "true",
    }
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": mime_type,
    }
    try:
        async with httpx.AsyncClient(timeout=_TRANSCRIBE_TIMEOUT_S) as client:
            resp = await client.post(
                _DEEPGRAM_LISTEN_URL,
                headers=headers,
                params=params,
                content=audio_bytes,
            )
            if resp.status_code >= 400:
                logger.error(
                    "deepgram error %s: %s", resp.status_code, resp.text[:200]
                )
                return ""
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("deepgram transcribe failed (%s)", type(exc).__name__)
        return ""
    except Exception:
        logger.exception("deepgram transcribe unexpected failure")
        return ""

    return _extract_transcript(body)


def _extract_transcript(body: dict) -> str:
    """Pull the first alternative's transcript out of a Deepgram listen response.

    Shape:
      {"results": {"channels": [{"alternatives": [{"transcript": "..."}]}]}}
    """
    try:
        channels = body.get("results", {}).get("channels", [])
        if not channels:
            return ""
        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            return ""
        transcript = alternatives[0].get("transcript", "")
        return str(transcript or "").strip()
    except (AttributeError, TypeError, IndexError, KeyError):
        logger.warning("deepgram: unexpected response shape")
        return ""
