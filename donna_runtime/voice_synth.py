"""ElevenLabs TTS + WhatsApp media upload for Donna's voice replies.

The synthesis hook reads the outbound buffer left by `send_burst_result`,
detects the `VoiceResponseMarker` sentinel, concatenates the text bodies of
the burst, synthesizes one ogg/opus voice note via ElevenLabs Flash v2.5,
uploads it to the WhatsApp Cloud Media API, and replaces the buffer with a
single `AudioMessage` flagged as a native voice note.

Failure modes degrade silently to text:
  - voice disabled                  → strip marker, leave text bodies intact
  - text bodies empty / over cap    → strip marker, leave text bodies intact
  - ElevenLabs / WA upload error    → strip marker, leave text bodies intact

Voice never blocks delivery.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging

import httpx

from config import settings
from delivery.messages import (
    AudioMessage,
    Delay,
    TextMessage,
    VoiceResponseMarker,
)
from delivery.whatsapp import WhatsAppChannel

from .hooks import _CURRENT_TRACE, _OUTBOUND_BUFFER

logger = logging.getLogger(__name__)

# When set to True (e.g. by api/voice_routes.py for live LiveKit calls),
# `maybe_synthesize_voice` strips the voice marker without calling
# ElevenLabs or WhatsApp media upload — TEXT is left in the buffer for
# the LiveKit ElevenLabs plugin to synthesize on the agent side.
_SKIP_VOICE_SYNTH: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "donna_skip_voice_synth", default=False
)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_OGG_OPUS_MIME = "audio/ogg; codecs=opus"
_OUTPUT_FORMAT = "opus_48000_32"   # ElevenLabs format string for ogg/opus 48kHz 32kbps
_TTS_TIMEOUT_S = 15.0


async def synthesize_tts(text: str) -> bytes:
    """POST to ElevenLabs, return ogg/opus bytes.

    Raises on any network or API error — caller is expected to fall back to text.
    """
    if not settings.elevenlabs_api_key:
        raise RuntimeError("elevenlabs_api_key not configured")

    url = _ELEVENLABS_TTS_URL.format(voice_id=settings.elevenlabs_voice_id)
    params = {"output_format": _OUTPUT_FORMAT}
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "accept": "audio/ogg",
    }
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model_id,
        "voice_settings": {"speed": settings.elevenlabs_voice_speed},
    }
    async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_S) as client:
        resp = await client.post(url, headers=headers, params=params, json=payload)
        if resp.status_code >= 400:
            logger.error(
                "elevenlabs tts error %s: %s", resp.status_code, resp.text[:200]
            )
            resp.raise_for_status()
        return resp.content


def _collect_text(buffer: list) -> str:
    """Join text bodies in the buffer (skipping markers and delays)."""
    parts: list[str] = []
    for item in buffer:
        if isinstance(item, TextMessage) and item.body:
            parts.append(item.body.strip())
    return " ".join(p for p in parts if p).strip()


def _strip_marker(buffer: list) -> None:
    """In-place: drop every VoiceResponseMarker, keep everything else."""
    kept = [m for m in buffer if not isinstance(m, VoiceResponseMarker)]
    buffer.clear()
    buffer.extend(kept)


def _user_asked_for_voice_this_turn() -> bool:
    """Belt to the PreToolUse-injection suspenders.

    Reads the trace's user_message and runs the same detector
    `pre_tool_hook._maybe_inject_voice_response` uses. Returns True when the
    user's current message contains an explicit voice request — in which case
    we synthesize even if the model never emitted the marker AND the SDK
    didn't honor the PreToolUse `updatedInput`.
    """
    trace = _CURRENT_TRACE.get()
    if trace is None:
        return False
    user_message = getattr(trace, "user_message", "") or ""
    from .voice_intent import detect_voice_request

    return detect_voice_request(user_message)


def _replace_with_audio(buffer: list, audio: AudioMessage) -> None:
    """In-place: clear the buffer and put one AudioMessage in it.

    Drops text bubbles (their content is now in the audio) and any markers.
    Keeps Delay markers — pacing still matters even before a voice note.
    """
    delays = [m for m in buffer if isinstance(m, Delay)]
    buffer.clear()
    buffer.extend([*delays, audio])


async def maybe_synthesize_voice(
    channel: WhatsAppChannel | None = None,
) -> None:
    """Detect a voice marker in the current outbound buffer, synthesize, mutate.

    No-op when no marker is present. Always leaves the buffer in a deliverable
    state — on any failure, the marker is stripped and the original text bursts
    are preserved (text fallback).

    Caller responsibility: invoke from `send_burst` AFTER `send_burst_result`
    has populated the buffer, BEFORE the brain loop terminates.
    """
    buffer = _OUTBOUND_BUFFER.get()
    if buffer is None:
        return

    if _SKIP_VOICE_SYNTH.get():
        # Live voice call (LiveKit): the agent's own ElevenLabs plugin
        # speaks the text. Strip the marker, keep text bodies, return.
        logger.info("voice synth: skipped (live voice channel)")
        _strip_marker(buffer)
        return

    has_marker = any(isinstance(m, VoiceResponseMarker) for m in buffer)
    forced_by_user_request = False
    if not has_marker:
        forced_by_user_request = _user_asked_for_voice_this_turn()
        if not forced_by_user_request:
            logger.info(
                "voice synth: no voice_response marker, no explicit voice ask (items=%d)",
                len(buffer),
            )
            return
        logger.info(
            "voice synth: forcing voice (user explicitly asked, model emitted text-only burst)"
        )
        # Inject a virtual marker so the rest of the function and downstream
        # observability treat this exactly like a model-emitted marker case.
        buffer.insert(0, VoiceResponseMarker())
    else:
        logger.info("voice synth: voice_response marker detected, synthesizing")

    if not settings.donna_voice_enabled:
        logger.info("voice synth: DONNA_VOICE_ENABLED=false — falling back to text")
        _strip_marker(buffer)
        return

    text = _collect_text(buffer)
    if not text:
        logger.warning("voice synth: marker present but no text bodies — fallback")
        _strip_marker(buffer)
        return

    if len(text) > settings.donna_voice_max_chars:
        logger.warning(
            "voice synth: text %d chars > cap %d — fallback to text",
            len(text), settings.donna_voice_max_chars,
        )
        _strip_marker(buffer)
        return

    wa = channel or WhatsAppChannel()
    try:
        audio_bytes = await synthesize_tts(text)
    except (httpx.HTTPError, RuntimeError, asyncio.TimeoutError) as exc:
        logger.warning("voice synth: TTS failed (%s) — fallback to text", type(exc).__name__)
        _strip_marker(buffer)
        return
    except Exception:
        logger.exception("voice synth: unexpected TTS failure — fallback to text")
        _strip_marker(buffer)
        return

    try:
        media_id = await wa.upload_media(audio_bytes, _OGG_OPUS_MIME)
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("voice synth: WA upload failed (%s) — fallback to text", type(exc).__name__)
        _strip_marker(buffer)
        return
    except Exception:
        logger.exception("voice synth: unexpected WA upload failure — fallback to text")
        _strip_marker(buffer)
        return

    audio = AudioMessage(media_id=media_id, voice=True)
    _replace_with_audio(buffer, audio)
    logger.info("voice synth: ok (chars=%d media_id=%s)", len(text), media_id[:8])
