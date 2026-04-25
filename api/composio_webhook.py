"""POST /webhooks/composio — Composio inbound events.

Source-of-truth surface for connection lifecycle and live ingest. Verifies
HMAC-SHA256 signature against COMPOSIO_WEBHOOK_SECRET, then dispatches by
`event` field. Phase 1 handles connection.complete / revoke / expired only;
gmail / calendar events are wired in Phase 2.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from backend.integrations import state
from backend.integrations.composio_client import verify_webhook_signature
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


_APP_TO_PRODUCT = {
    "GMAIL": "gmail",
    "GOOGLECALENDAR": "calendar",
}


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
        await state.mark_connected(
            user_id,
            "google",
            product,
            connection_id=payload.get("connection_id") or "",
        )
        # Live trigger subscription + bootstrap enqueue happen in P2/P3.
        return {"ok": True}

    if event in {"connection.revoked", "connection.expired"}:
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product:
            await state.mark_revoked(user_id, "google", product)
        return {"ok": True}

    # gmail / calendar events handled in P2; for now, ack and drop.
    logger.info("composio_webhook: unhandled event=%r", event)
    return {"ok": True, "unhandled": event}
