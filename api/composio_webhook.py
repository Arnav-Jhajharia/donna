"""POST /webhooks/composio — Composio inbound events.

Source-of-truth surface for connection lifecycle and live ingest. Verifies
HMAC-SHA256 signature against COMPOSIO_WEBHOOK_SECRET, then dispatches by
`event` field. Handles connection lifecycle (complete/revoke/expired) and
live ingest for gmail.new_message and calendar.event.{created,updated,deleted}.

Calendar event payloads ride on the top-level `data` field rather than `event`
to avoid colliding with the event-type discriminator.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from backend.integrations import state
from backend.integrations.biography_synthesis import synthesize_biography
from backend.integrations.bootstrap_calendar import bootstrap_calendar
from backend.integrations.bootstrap_gmail import (
    bootstrap_30d_important,
    bootstrap_90d_aggregates,
    bootstrap_today_dense,
)
from backend.integrations.calendar_ingest import (
    delete_calendar_event,
    ingest_calendar_event,
)
from backend.integrations.composio_client import (
    TRIGGER_CALENDAR_EVENT_CREATED,
    TRIGGER_CALENDAR_EVENT_DELETED,
    TRIGGER_CALENDAR_EVENT_UPDATED,
    TRIGGER_GMAIL_NEW_MESSAGE,
    ComposioClient,
    NormalizedGmailMessage,
    verify_webhook_signature,
)
from backend.integrations.gmail_ingest import ingest_gmail_message
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


_APP_TO_PRODUCT = {
    "GMAIL": "gmail",
    "GOOGLECALENDAR": "calendar",
}

_CALENDAR_UPSERT_EVENTS = {"calendar.event.created", "calendar.event.updated"}

_PRODUCT_TRIGGERS = {
    "gmail": (TRIGGER_GMAIL_NEW_MESSAGE,),
    "calendar": (
        TRIGGER_CALENDAR_EVENT_CREATED,
        TRIGGER_CALENDAR_EVENT_UPDATED,
        TRIGGER_CALENDAR_EVENT_DELETED,
    ),
}


async def run_bootstrap_async(user_id: str) -> None:
    """Run all bootstrap stages plus biography synthesis. Fire-and-forget."""
    try:
        await bootstrap_today_dense(user_id)
        await bootstrap_30d_important(user_id)
        await bootstrap_calendar(user_id)
        aggregates = await bootstrap_90d_aggregates(user_id)

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import EmailMessage

        async with async_session() as s:
            rows = (
                await s.execute(
                    select(EmailMessage)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.ingest_depth == "full")
                    .where(EmailMessage.body_stored.is_(True))
                )
            ).scalars().all()
        msgs = [
            NormalizedGmailMessage(
                gmail_message_id=r.gmail_message_id,
                thread_id=r.thread_id,
                from_address=r.from_address,
                from_name=r.from_name,
                to_addresses=r.to_addresses,
                cc_addresses=r.cc_addresses,
                subject=r.subject,
                snippet=r.snippet,
                body_text=r.body_text,
                labels=r.labels,
                is_important=r.is_important,
                is_starred=r.is_starred,
                is_sent=r.is_sent,
                internal_date=r.internal_date,
            )
            for r in rows
        ]
        await synthesize_biography(user_id, msgs, aggregates)
    except Exception:
        logger.exception("bootstrap failed user=%s", user_id)


@router.post("/webhooks/composio")
async def composio_webhook(
    request: Request,
    x_composio_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    secret = settings.composio_webhook_secret or ""
    if not verify_webhook_signature(body, x_composio_signature or "", secret):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad json")

    event = payload.get("event")
    user_id = payload.get("user_id")
    if not event or not user_id:
        raise HTTPException(status_code=400, detail="missing fields")

    if event == "connection.complete":
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product is None:
            logger.warning("composio_webhook: unknown app=%r", app)
            return {"ok": True, "ignored": True}
        connection_id = payload.get("connection_id") or ""
        await state.mark_connected(
            user_id,
            "google",
            product,
            connection_id=connection_id,
        )
        triggers = _PRODUCT_TRIGGERS.get(product, ())
        if triggers and connection_id:
            client = ComposioClient(api_key=settings.composio_api_key or "")
            await client.subscribe_triggers(
                user_id=user_id,
                connection_id=connection_id,
                trigger_names=triggers,
            )
        asyncio.create_task(run_bootstrap_async(user_id))
        return {"ok": True}

    if event in {"connection.revoked", "connection.expired"}:
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product:
            await state.mark_revoked(user_id, "google", product)
        return {"ok": True}

    if event == "gmail.new_message":
        message_id = payload.get("message_id")
        if not message_id:
            raise HTTPException(status_code=400, detail="missing message_id")
        client = ComposioClient(api_key=settings.composio_api_key or "")
        msg = await client.fetch_gmail_message(
            user_id=user_id, message_id=message_id, include_body=True
        )
        await ingest_gmail_message(user_id, msg)
        await state.touch_synced(user_id, "google", "gmail")
        return {"ok": True}

    if event in _CALENDAR_UPSERT_EVENTS:
        ev = payload.get("data") or {}
        if not ev.get("id"):
            raise HTTPException(status_code=400, detail="missing event id")
        await ingest_calendar_event(user_id, ev)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}

    if event == "calendar.event.deleted":
        ev = payload.get("data") or {}
        ev_id = ev.get("id") or payload.get("event_id")
        if not ev_id:
            raise HTTPException(status_code=400, detail="missing event id")
        await delete_calendar_event(user_id, ev_id)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}

    logger.info("composio_webhook: unhandled event=%r", event)
    return {"ok": True, "unhandled": event}
