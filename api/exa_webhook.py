"""Exa webset monitor webhook receiver.

Exa POSTs to this endpoint when a monitor produces new items. The body
is JSON; we verify an HMAC-SHA256 signature in the ``x-exa-signature``
header against ``EXA_WEBHOOK_SECRET``. Verified payloads are forwarded
to ``record_monitor_hit`` which enqueues per-item proactive_signals
rows.

Security:
- Reject requests with no signature header.
- Reject requests whose signature does not match.
- Use ``hmac.compare_digest`` for constant-time comparison.

Operationally, the secret is configured in Railway env. Set
``EXA_WEBHOOK_SECRET`` and supply it to Exa when registering the
monitor's webhook url.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from backend.web.proactive.subscriptions import record_monitor_hit

logger = logging.getLogger(__name__)
router = APIRouter()


def _expected_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/api/exa/monitor_callback")
async def exa_monitor_callback(request: Request) -> dict[str, int]:
    secret = (os.environ.get("EXA_WEBHOOK_SECRET") or "").strip()
    if not secret:
        logger.warning("exa webhook called but EXA_WEBHOOK_SECRET unset")
        raise HTTPException(status_code=503, detail="webhook unconfigured")

    sig_header = (request.headers.get("x-exa-signature") or "").strip()
    if not sig_header:
        raise HTTPException(status_code=401, detail="missing signature")

    body = await request.body()
    expected = _expected_signature(body, secret)
    if not hmac.compare_digest(sig_header, expected):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload not object")

    written = await record_monitor_hit(payload)
    return {"recorded": int(written)}
