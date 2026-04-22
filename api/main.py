"""FastAPI entrypoint — webhook + per-phone cancel-and-restart dispatcher.

Ported from backend-v2 and trimmed for the text-only MVP:
  - Webhook verify (GET /webhook) and handler (POST /webhook)
  - Per-phone cancel-and-restart: rapid-fire messages cancel the in-flight
    pipeline (if it hasn't entered send phase) and restart with merged payloads
  - Dispatches to donna_runtime.brain.donna_turn in place of the old LangGraph
  - Backfills assistant wamid on ChatMessage rows for swipe-reply context

Dropped for MVP: TTS, Supabase storage, document poll-and-follow-up,
auth/dashboard/signup routers, background nightly/proactive loops.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging

from donna_runtime.env import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from config import settings
from db.migrations import create_tables
from db.models import ChatMessage
from db.session import async_session
from delivery.messages import Delay, TextMessage
from delivery.whatsapp import WhatsAppChannel
from graph import state_from_payload, user_lookup
from ingress.node import enrich as enrich_state
from ingress.payload import IngressPayload
from ingress.whatsapp import parse_webhook
from donna_runtime.brain import donna_turn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-36s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Donna (Claw-Code)")
_wa = WhatsAppChannel()


# ── Per-phone pipeline coordination ──────────────────────────────────────────
_active_tasks: dict[str, asyncio.Task] = {}
_pending_payloads: dict[str, list[IngressPayload]] = {}
_sending_phase: dict[str, bool] = {}
_phone_locks: dict[str, asyncio.Lock] = {}


def _lock_for(phone: str) -> asyncio.Lock:
    lock = _phone_locks.get(phone)
    if lock is None:
        lock = asyncio.Lock()
        _phone_locks[phone] = lock
    return lock


def _merge_payloads(payloads: list[IngressPayload]) -> IngressPayload:
    if len(payloads) == 1:
        return payloads[0]
    base = payloads[-1]
    texts = [p.message for p in payloads if p.message]
    combined = "\n".join(texts) if texts else base.message
    media = next(
        (
            p for p in reversed(payloads)
            if (p.voice and p.voice.file_bytes)
            or (p.image and p.image.file_bytes)
            or (p.document and p.document.file_bytes)
        ),
        None,
    )
    if media is None or media is base:
        return dataclasses.replace(base, message=combined)
    return dataclasses.replace(
        base,
        message=combined,
        message_type=media.message_type,
        voice=media.voice,
        image=media.image,
        document=media.document,
    )


async def _save_user_message(user_id: str, content: str, wa_message_id: str | None) -> None:
    if not content:
        return
    try:
        async with async_session() as session:
            session.add(ChatMessage(
                user_id=user_id, role="user", content=content, wa_message_id=wa_message_id,
            ))
            await session.commit()
    except Exception:
        logger.exception("save_user_message failed for %s", user_id[:8])


async def _save_assistant_message(user_id: str, content: str) -> None:
    if not content:
        return
    try:
        async with async_session() as session:
            session.add(ChatMessage(user_id=user_id, role="assistant", content=content))
            await session.commit()
    except Exception:
        logger.exception("save_assistant_message failed for %s", user_id[:8])


async def _backfill_assistant_wamid(user_id: str, wamid: str) -> None:
    try:
        from sqlalchemy import text as sql_text
        async with async_session() as session:
            await session.execute(
                sql_text("""
                    UPDATE chat_messages SET wa_message_id = :wamid
                    WHERE id = (
                        SELECT id FROM chat_messages
                        WHERE user_id = :uid AND role = 'assistant'
                          AND wa_message_id IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    )
                """),
                {"wamid": wamid, "uid": user_id},
            )
            await session.commit()
    except Exception:
        logger.exception("backfill_assistant_wamid failed for user %s", user_id[:8])


async def _run_pipeline(phone: str, payloads: list[IngressPayload]) -> None:
    try:
        merged = _merge_payloads(payloads)
        if len(payloads) > 1:
            logger.info("pipeline: merged %d payloads for %s", len(payloads), phone[:6])

        state = state_from_payload(merged)
        state = await user_lookup(state)
        state = await enrich_state(state)

        # Persist the user's inbound message before the brain runs so
        # reply-resolution works for future turns.
        await _save_user_message(
            state["user_id"], state.get("raw_input") or "", merged.platform_message_id,
        )

        try:
            state = await donna_turn(state)
        except Exception:
            logger.exception("brain failed for %s; sending fallback", phone[:6])
            state["_outbound"] = [TextMessage(body="hm, one sec")]

        outbound = state.get("_outbound") or []
        if not outbound:
            return

        platform_msg_id = merged.platform_message_id
        if platform_msg_id:
            for msg in outbound:
                if not isinstance(msg, Delay) and hasattr(msg, "reply_to_message_id"):
                    msg.reply_to_message_id = platform_msg_id
                    break

        async with _lock_for(phone):
            _sending_phase[phone] = True

        # Save assistant messages before send so _backfill can find them.
        for msg in outbound:
            if isinstance(msg, TextMessage) and msg.body:
                await _save_assistant_message(state["user_id"], msg.body)

        wamids = await _wa.send_many(phone, outbound)
        if wamids:
            await _backfill_assistant_wamid(state["user_id"], wamids[0])

    except asyncio.CancelledError:
        logger.info("pipeline cancelled for %s (new message arrived)", phone[:6])
        raise
    except Exception:
        logger.exception("pipeline failed for %s", phone[:6])
    finally:
        async with _lock_for(phone):
            if _active_tasks.get(phone) is asyncio.current_task():
                _active_tasks.pop(phone, None)
                _pending_payloads.pop(phone, None)
                _sending_phase.pop(phone, None)


async def _dispatch(payload: IngressPayload) -> None:
    phone = payload.phone
    async with _lock_for(phone):
        existing = _active_tasks.get(phone)
        is_sending = _sending_phase.get(phone, False)

        if existing and not existing.done() and not is_sending:
            pending = list(_pending_payloads.get(phone, []))
            pending.append(payload)
            _pending_payloads[phone] = pending
            existing.cancel()
            logger.info(
                "dispatch: cancelling in-flight for %s, restarting with %d merged",
                phone[:6], len(pending),
            )
            task = asyncio.create_task(_run_pipeline(phone, list(pending)))
            _active_tasks[phone] = task
        else:
            _pending_payloads[phone] = [payload]
            task = asyncio.create_task(_run_pipeline(phone, [payload]))
            _active_tasks[phone] = task


@app.on_event("startup")
async def _startup() -> None:
    try:
        await create_tables()
    except Exception:
        logger.exception("startup: create_tables failed (DB not reachable?) — continuing")
    logger.info("donna (claw-code) started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(request: Request) -> PlainTextResponse:
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge") or ""
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    return PlainTextResponse("forbidden", status_code=403)


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    body = await request.json()

    if settings.relay_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{settings.relay_url}/webhook", json=body)
            logger.info("relay: forwarded webhook to %s", settings.relay_url)
        except Exception:
            logger.exception("relay: failed to forward")
        return {"status": "relayed"}

    payloads = await parse_webhook(body)
    if not payloads:
        return {"status": "ok"}

    for payload in payloads:
        if payload.platform_message_id:
            await _wa.send_typing(payload.phone, payload.platform_message_id)
        await _dispatch(payload)

    return {"status": "ok"}
