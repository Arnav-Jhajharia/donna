"""Voice surface — OpenAI-compatible streaming chat-completions for the
LiveKit voice agent.

The LiveKit agent worker (`voice_callbot.agent`) handles audio: SIP /
WebRTC, Deepgram STT, ElevenLabs TTS, VAD, turn-taking. Per finalized
user utterance it hits this endpoint with an OpenAI chat-completions
request; we run donna's full BRAIN loop and stream the reply back as
SSE deltas.

Endpoints
---------
POST /voice/llm/chat
    OpenAI-compatible streaming endpoint hit per finalized user turn.
POST /voice/events
    Out-of-band webhook for call.start / call.end / status updates.
GET  /voice/health
    Liveness ping.

Auth
----
Caller signs every request with header `x-voice-secret: <VOICE_BRAIN_SECRET>`.
We compare against env. Reject mismatches with 401.

For backwards-compat with code that still calls `/vapi/...` (the old
name, before this surface was renamed), the same handlers are also
mounted under `/vapi`. Header `x-vapi-secret` is accepted as an alias.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from delivery.messages import TextMessage
from donna_runtime.brain import donna_turn
from donna_runtime.config import DonnaAgentConfig
from donna_runtime.post_call import run_post_call
from donna_runtime.voice_brain import stream_voice_reply
from donna_runtime.voice_synth import _SKIP_VOICE_SYNTH

logger = logging.getLogger(__name__)


def _verify_secret(
    x_voice_secret: str | None = None,
    x_vapi_secret: str | None = None,
    authorization: str | None = None,
) -> None:
    expected = (
        os.environ.get("VOICE_BRAIN_SECRET")
        or os.environ.get("VAPI_WEBHOOK_SECRET")  # legacy name
    )
    if not expected:
        raise HTTPException(500, "VOICE_BRAIN_SECRET not configured")
    bearer: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    provided = x_voice_secret or x_vapi_secret or bearer
    if provided != expected:
        raise HTTPException(401, "bad voice secret")


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                return " ".join(parts).strip()
    return ""


def _extract_system_overlay(messages: list[dict]) -> str:
    """Pull system messages out of the OpenAI-style payload. The
    voice agent embeds a voice-register prompt here — register, audio
    tags, brevity rules. We append it to donna's brain context so it
    actually takes effect."""
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
    return "\n\n".join(parts)


def _phone_from_call(call: dict | None) -> str:
    if not call:
        return "unknown"
    customer = call.get("customer") or {}
    return customer.get("number") or call.get("from") or "unknown"


def _user_id_from_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return f"voice:{digits}" if digits else "voice:unknown"


def _outbound_text(state: dict) -> str:
    outbound = state.get("_outbound") or []
    parts: list[str] = []
    for item in outbound:
        if isinstance(item, TextMessage) and item.body:
            parts.append(item.body)
        elif isinstance(item, str) and item:
            parts.append(item)
    return "\n".join(parts).strip()


def _sse_chunk(text: str, model: str, completion_id: str) -> bytes:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": text},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _sse_done(model: str, completion_id: str) -> bytes:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return (
        f"data: {json.dumps(payload)}\n\n".encode() + b"data: [DONE]\n\n"
    )


# ─────────────────────── handlers (shared) ────────────────────────────


async def _handle_chat(
    request: Request,
    x_voice_secret: str | None = None,
    x_vapi_secret: str | None = None,
    authorization: str | None = None,
) -> StreamingResponse:
    _verify_secret(x_voice_secret, x_vapi_secret, authorization)
    body = await request.json()

    messages = body.get("messages") or []
    raw = _last_user_text(messages)
    voice_overlay = _extract_system_overlay(messages)
    model = body.get("model") or "donna-voice"

    call = body.get("call") or {}
    phone = _phone_from_call(call)
    user_id = _user_id_from_phone(phone)
    completion_id = f"cmpl-{uuid.uuid4().hex[:16]}"

    logger.info(
        "voice: turn user=%s phone=%s chars=%d call_id=%s overlay=%d",
        user_id, phone, len(raw), call.get("id", "?"), len(voice_overlay),
    )

    use_full_brain = os.environ.get("VOICE_USE_FULL_BRAIN", "0") == "1"

    async def generator() -> AsyncIterator[bytes]:
        if use_full_brain:
            # Slow path — full WhatsApp BRAIN loop with tools + memory.
            # Off by default for voice (5–10s TTFB). Enable via env when
            # debugging tool-call behavior.
            state = {
                "raw_input": raw,
                "user_id": user_id,
                "phone": phone,
                "platform_message_id": call.get("id"),
                "channel": "voice",
            }
            cfg = (
                DonnaAgentConfig(system_context=voice_overlay)
                if voice_overlay
                else DonnaAgentConfig()
            )
            token = _SKIP_VOICE_SYNTH.set(True)
            try:
                result = await donna_turn(state, cfg)
                text = _outbound_text(result) or "mm. say that?"
                logger.info("voice: full-brain reply len=%d preview=%r", len(text), text[:120])
            except Exception:
                logger.exception("voice: full-brain failure")
                text = "give me a sec, line glitched."
            finally:
                _SKIP_VOICE_SYNTH.reset(token)
            yield _sse_chunk(text, model, completion_id)
            yield _sse_done(model, completion_id)
            return

        # Fast path — direct Haiku 4.5 stream, no tools, voice register only.
        # Streams tokens to LiveKit as they arrive so TTS starts speaking
        # immediately on the first sentence boundary.
        try:
            async for delta in stream_voice_reply(
                user_id=user_id,
                user_text=raw,
                extra_system=voice_overlay,
                call_id=call.get("id"),
                phone=phone,
            ):
                yield _sse_chunk(delta, model, completion_id)
        except Exception:
            logger.exception("voice: fast-path brain failure")
            yield _sse_chunk("give me a sec, line glitched.", model, completion_id)
        yield _sse_done(model, completion_id)

    return StreamingResponse(generator(), media_type="text/event-stream")


async def _handle_events(
    request: Request,
    x_voice_secret: str | None = None,
    x_vapi_secret: str | None = None,
    authorization: str | None = None,
) -> dict:
    _verify_secret(x_voice_secret, x_vapi_secret, authorization)
    body = await request.json()
    msg = body.get("message") or {}
    msg_type = msg.get("type")

    call = msg.get("call") or {}
    call_id = call.get("id")
    phone = _phone_from_call(call)

    logger.info("voice: event type=%s call_id=%s phone=%s", msg_type, call_id, phone)

    if msg_type == "end-of-call-report":
        # Hook point for post-turn memory flush / commitment summarization
        # / callback scheduling. The WhatsApp pipeline does these via
        # post-turn hooks; voice should reuse the same surfaces.
        logger.info(
            "voice: end-of-call call_id=%s duration=%s ended_reason=%s",
            call_id,
            msg.get("durationSeconds"),
            msg.get("endedReason"),
        )

    return {"ok": True}


async def _handle_post_call(
    request: Request,
    x_voice_secret: str | None = None,
    x_vapi_secret: str | None = None,
    authorization: str | None = None,
) -> dict:
    """Fired by the agent worker on session close. Runs the FULL
    BRAIN loop over the call transcript: extracts commitments,
    schedules anything promised, optionally sends a WhatsApp summary.
    Non-blocking from the agent's POV — fires-and-forgets."""
    _verify_secret(x_voice_secret, x_vapi_secret, authorization)
    body = await request.json()
    call_id = body.get("call_id") or "unknown"
    user_id = body.get("user_id") or "voice:unknown"
    phone = body.get("phone") or "unknown"

    logger.info(
        "voice: post-call hook fired call_id=%s user_id=%s",
        call_id, user_id,
    )

    # Run synchronously in this request — the caller (LiveKit agent)
    # is also async. If we wanted true fire-and-forget we'd schedule
    # via asyncio.create_task, but the agent already calls this in a
    # detached task so blocking here is fine.
    try:
        return await run_post_call(call_id, user_id, phone)
    except Exception as e:
        logger.exception("voice: post-call run failed")
        return {"ok": False, "error": str(e)}


# ─────────────────────── primary surface (/voice) ─────────────────────

router = APIRouter(prefix="/voice")


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "surface": "voice"}


@router.post("/chat/completions")
@router.post("/llm/chat")
async def chat_completions(
    request: Request,
    x_voice_secret: str | None = Header(default=None, alias="x-voice-secret"),
    x_vapi_secret: str | None = Header(default=None, alias="x-vapi-secret"),
    authorization: str | None = Header(default=None, alias="authorization"),
) -> StreamingResponse:
    return await _handle_chat(request, x_voice_secret, x_vapi_secret, authorization)


@router.post("/events")
async def server_events(
    request: Request,
    x_voice_secret: str | None = Header(default=None, alias="x-voice-secret"),
    x_vapi_secret: str | None = Header(default=None, alias="x-vapi-secret"),
    authorization: str | None = Header(default=None, alias="authorization"),
) -> dict:
    return await _handle_events(request, x_voice_secret, x_vapi_secret, authorization)


@router.post("/post-call")
async def post_call(
    request: Request,
    x_voice_secret: str | None = Header(default=None, alias="x-voice-secret"),
    x_vapi_secret: str | None = Header(default=None, alias="x-vapi-secret"),
    authorization: str | None = Header(default=None, alias="authorization"),
) -> dict:
    return await _handle_post_call(request, x_voice_secret, x_vapi_secret, authorization)


# ─────────────────────── legacy alias surface (/vapi) ─────────────────
#
# Old clients (and the SETUP docs from earlier in this session) hit
# /vapi/chat/completions. Keep the alias so nothing breaks during the
# rename. Delete once all callers have moved.

legacy_router = APIRouter(prefix="/vapi")


@legacy_router.get("/health")
async def legacy_health() -> dict:
    return {"ok": True, "surface": "voice", "alias": "vapi"}


@legacy_router.post("/chat/completions")
async def legacy_chat_completions(
    request: Request,
    x_voice_secret: str | None = Header(default=None, alias="x-voice-secret"),
    x_vapi_secret: str | None = Header(default=None, alias="x-vapi-secret"),
    authorization: str | None = Header(default=None, alias="authorization"),
) -> StreamingResponse:
    return await _handle_chat(request, x_voice_secret, x_vapi_secret, authorization)


@legacy_router.post("/server-events")
async def legacy_server_events(
    request: Request,
    x_voice_secret: str | None = Header(default=None, alias="x-voice-secret"),
    x_vapi_secret: str | None = Header(default=None, alias="x-vapi-secret"),
    authorization: str | None = Header(default=None, alias="authorization"),
) -> dict:
    return await _handle_events(request, x_voice_secret, x_vapi_secret, authorization)
