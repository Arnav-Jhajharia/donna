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
import os

from donna_runtime.env import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from config import settings
from db.inbound import (
    fetch_queued_by_phone,
    insert_inbound,
    mark_failed,
    mark_processed,
)
from db.migrations import create_tables
from db.models import ChatMessage
from db.session import async_session
from delivery.messages import Delay, TextMessage
from delivery.whatsapp import WhatsAppChannel
from api.graph import state_from_payload, user_lookup
from ingress.node import enrich as enrich_state
from ingress.payload import IngressPayload
from ingress.whatsapp import _parse_one, parse_webhook
from donna_runtime.brain import donna_turn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-36s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Donna (Claw-Code)")

# Composio webhook ingest (OAuth completions, gmail/calendar events).
from api.composio_webhook import router as _composio_router  # noqa: E402

app.include_router(_composio_router)

_wa = WhatsAppChannel()
_brief_refresh_task: asyncio.Task | None = None


# ── Per-phone pipeline coordination ──────────────────────────────────────────
# Each pending item is (payload, inbox_row_id). row_id may be None when the
# durable insert failed — the pipeline still runs, we just can't mark the row.
_DispatchItem = tuple[IngressPayload, str | None]

_active_tasks: dict[str, asyncio.Task] = {}
_pending_items: dict[str, list[_DispatchItem]] = {}
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


async def _run_pipeline(phone: str, items: list[_DispatchItem]) -> None:
    payloads = [p for p, _ in items]
    row_ids = [rid for _, rid in items if rid]
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
            # Auto-stamp quote-reply on the first non-Delay item only when the
            # model didn't pick one itself. Per-bubble reply_to_message_id is
            # part of the send_burst schema now, so the model is the
            # authoritative chooser; this is just a fallback for back-compat.
            for msg in outbound:
                if isinstance(msg, Delay) or not hasattr(msg, "reply_to_message_id"):
                    continue
                if getattr(msg, "reply_to_message_id", None):
                    break
                msg.reply_to_message_id = platform_msg_id
                break

        async with _lock_for(phone):
            _sending_phase[phone] = True

        # Save assistant messages before send so _backfill can find them.
        # Renders CTAs / lists / images to plain text so quote-reply context
        # survives across non-text turns.
        from donna_runtime.tool_logic import render_outbound_text
        for msg in outbound:
            body = render_outbound_text(msg)
            if body:
                await _save_assistant_message(state["user_id"], body)

        wamids = await _wa.send_many(phone, outbound)
        if wamids:
            await _backfill_assistant_wamid(state["user_id"], wamids[0])

        await mark_processed(row_ids)

    except asyncio.CancelledError:
        logger.info("pipeline cancelled for %s (new message arrived)", phone[:6])
        # Leave rows as 'queued' so the restart task picks them up.
        raise
    except Exception as exc:
        logger.exception("pipeline failed for %s", phone[:6])
        await mark_failed(row_ids, f"{type(exc).__name__}: {exc}")
    finally:
        async with _lock_for(phone):
            if _active_tasks.get(phone) is asyncio.current_task():
                _active_tasks.pop(phone, None)
                _pending_items.pop(phone, None)
                _sending_phase.pop(phone, None)


async def _dispatch(payload: IngressPayload, row_id: str | None) -> None:
    phone = payload.phone
    item: _DispatchItem = (payload, row_id)
    async with _lock_for(phone):
        existing = _active_tasks.get(phone)
        is_sending = _sending_phase.get(phone, False)

        if existing and not existing.done() and not is_sending:
            pending = list(_pending_items.get(phone, []))
            pending.append(item)
            _pending_items[phone] = pending
            existing.cancel()
            logger.info(
                "dispatch: cancelling in-flight for %s, restarting with %d merged",
                phone[:6], len(pending),
            )
            task = asyncio.create_task(_run_pipeline(phone, list(pending)))
            _active_tasks[phone] = task
        else:
            _pending_items[phone] = [item]
            task = asyncio.create_task(_run_pipeline(phone, [item]))
            _active_tasks[phone] = task


async def _replay_queued_inbox() -> None:
    """Re-dispatch every still-queued inbox row from a prior process.

    Rebuilds payloads via ingress.whatsapp._parse_one (bypassing Meta dedup,
    since these rows are known-real). Rows that fail to parse are marked
    failed so they don't block subsequent replays.
    """
    grouped = await fetch_queued_by_phone()
    if not grouped:
        return
    total = sum(len(rows) for rows in grouped.values())
    logger.info("replay: re-dispatching %d queued rows across %d phones", total, len(grouped))

    for phone, rows in grouped.items():
        for row in rows:
            body = row.body or {}
            message = body.get("message") or {}
            value = body.get("value") or {}
            try:
                payload = await _parse_one(message, value)
            except Exception as exc:
                logger.exception("replay: parse failed for row %s", row.id)
                await mark_failed([row.id], f"replay_parse:{type(exc).__name__}:{exc}")
                continue
            if payload is None:
                await mark_failed([row.id], "replay_parse:returned_none")
                continue
            await _dispatch(payload, row.id)


@app.on_event("startup")
async def _startup() -> None:
    global _brief_refresh_task
    try:
        await create_tables()
    except Exception:
        logger.exception("startup: create_tables failed (DB not reachable?) — continuing")
    try:
        await _replay_queued_inbox()
    except Exception:
        logger.exception("startup: inbox replay failed — continuing")
    if os.environ.get("DONNA_BRIEF_REFRESH") == "1":
        try:
            from backend.memory.jobs.temporal_refresh import run_forever as brief_run_forever

            interval_s = float(os.environ.get("DONNA_BRIEF_REFRESH_INTERVAL_S") or 7200.0)
            active_days = int(os.environ.get("DONNA_BRIEF_REFRESH_ACTIVE_DAYS") or 14)
            _brief_refresh_task = asyncio.create_task(
                brief_run_forever(
                    poll_interval_s=interval_s,
                    active_within_days=active_days,
                ),
                name="brief_refresh",
            )
            logger.info(
                "startup: brief refresh enabled (interval=%.0fs, active_within_days=%d)",
                interval_s, active_days,
            )
        except Exception:
            logger.exception("startup: failed to start brief refresh")
    logger.info("donna (claw-code) started")


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _brief_refresh_task
    if _brief_refresh_task is not None:
        _brief_refresh_task.cancel()
        try:
            await _brief_refresh_task
        except Exception:
            pass
        _brief_refresh_task = None


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


def _parse_dev_phone_numbers(raw: str) -> set[str]:
    return {p.strip().lstrip("+") for p in raw.split(",") if p.strip()}


def _split_webhook_by_phone(body: dict, dev_phones: set[str]) -> tuple[dict | None, dict | None]:
    """Split a WA Cloud API webhook body by sender phone.

    Returns (dev_body, prod_body). Either may be None when one side has
    nothing. Status updates and other non-message changes pass to prod by
    default. Each body preserves the entry/changes/value envelope so the
    receiving instance can call parse_webhook directly.
    """
    if not dev_phones:
        return None, body

    dev_entries: list[dict] = []
    prod_entries: list[dict] = []

    for entry in body.get("entry", []):
        dev_changes: list[dict] = []
        prod_changes: list[dict] = []
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages") or []
            if not messages:
                prod_changes.append(change)
                continue

            dev_msgs = [m for m in messages if str(m.get("from", "")).lstrip("+") in dev_phones]
            prod_msgs = [m for m in messages if str(m.get("from", "")).lstrip("+") not in dev_phones]
            contacts = value.get("contacts") or []

            if dev_msgs:
                dev_value = {**value, "messages": dev_msgs}
                dev_contacts = [c for c in contacts if str(c.get("wa_id", "")).lstrip("+") in dev_phones]
                if dev_contacts:
                    dev_value["contacts"] = dev_contacts
                dev_changes.append({**change, "value": dev_value})
            if prod_msgs:
                prod_value = {**value, "messages": prod_msgs}
                prod_contacts = [c for c in contacts if str(c.get("wa_id", "")).lstrip("+") not in dev_phones]
                if prod_contacts:
                    prod_value["contacts"] = prod_contacts
                prod_changes.append({**change, "value": prod_value})

        if dev_changes:
            dev_entries.append({**entry, "changes": dev_changes})
        if prod_changes:
            prod_entries.append({**entry, "changes": prod_changes})

    dev_body = {**body, "entry": dev_entries} if dev_entries else None
    prod_body = {**body, "entry": prod_entries} if prod_entries else None
    return dev_body, prod_body


async def _forward_webhook(target_url: str, body: dict, label: str) -> None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{target_url.rstrip('/')}/webhook", json=body)
        logger.info("%s: forwarded webhook to %s", label, target_url)
    except Exception:
        logger.exception("%s: failed to forward to %s", label, target_url)


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    body = await request.json()

    # All-or-nothing relay (existing behavior).
    if settings.relay_url:
        await _forward_webhook(settings.relay_url, body, "relay")
        return {"status": "relayed"}

    # Per-phone dev re-routing. If any messages match dev phones, peel them
    # off and forward to the dev tunnel; continue processing the rest here.
    if settings.dev_relay_url and settings.dev_phone_numbers:
        dev_phones = _parse_dev_phone_numbers(settings.dev_phone_numbers)
        dev_body, prod_body = _split_webhook_by_phone(body, dev_phones)
        if dev_body is not None:
            await _forward_webhook(settings.dev_relay_url, dev_body, "dev_relay")
        body = prod_body if prod_body is not None else {"entry": []}

    payloads = await parse_webhook(body)
    if not payloads:
        return {"status": "ok"}

    raw_messages = _index_raw_messages(body)

    for payload in payloads:
        wa_id = payload.platform_message_id
        raw = raw_messages.get(wa_id) if wa_id else None
        row_id = None
        if raw is not None:
            row_id = await insert_inbound(
                phone=payload.phone,
                wa_message_id=wa_id,
                message=raw["message"],
                value=raw["value"],
            )

        if wa_id:
            # Typing indicator is best-effort and can stall the webhook ack
            # under WA API slowness — fire it and move on.
            asyncio.create_task(_wa.send_typing(payload.phone, wa_id))

        await _dispatch(payload, row_id)

    return {"status": "ok"}


def _index_raw_messages(body: dict) -> dict[str, dict]:
    """Index raw WA message dicts by wa_message_id for durable persistence.

    Returns {wa_id: {"message": <raw msg>, "value": <raw value>}}. Matches
    the envelope stored in InboundMessage.body so startup replay can
    reconstruct an IngressPayload via ingress.whatsapp._parse_one.
    """
    indexed: dict[str, dict] = {}
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                wa_id = message.get("id")
                if wa_id:
                    indexed[wa_id] = {"message": message, "value": value}
    return indexed
