"""Brain integration hook (placeholder for phase 2).

The donna-voice agent runs voice as a self-contained service in phase 1
— LiteLLM proxy is the LLM; tool calls are not wired. Phase 2 connects
this back to donna's BRAIN node so calls trigger memory writes,
schedule reminders, and post WhatsApp follow-ups when warranted.

Two integration points are stubbed here:

    notify_call_start(call_id, user_id, phone, direction)
        Tells the brain a call is in progress. Lets it skip proactive
        WhatsApp pushes during the call window.

    notify_call_end(call_id, user_id, phone, transcript)
        Fires the post-call brain. Brain extracts commitments,
        schedules anything promised, optionally sends a WhatsApp
        recap. Same shape as donna_runtime.post_call.run_post_call.

In phase 1 these are HTTP POSTs to BRAIN_HOOK_URL (defaults to the
existing donna API at /voice/post-call). When BRAIN_HOOK_URL is unset,
they no-op.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


def _hook_url() -> str:
    return os.environ.get("BRAIN_HOOK_URL", "").rstrip("/")


def _hook_secret() -> str:
    return os.environ.get("VOICE_BRAIN_SECRET", "")


async def notify_call_start(
    call_id: str,
    user_id: str,
    phone: str,
    direction: str,
) -> None:
    base = _hook_url()
    if not base:
        return
    payload = {
        "event": "call_start",
        "call_id": call_id,
        "user_id": user_id,
        "phone": phone,
        "direction": direction,
    }
    await _post(f"{base}/voice/events", payload, action="call_start")


async def notify_call_end(
    call_id: str,
    user_id: str,
    phone: str,
    transcript_summary: str | None = None,
    duration_seconds: int | None = None,
    ended_reason: str | None = None,
) -> None:
    base = _hook_url()
    if not base:
        return
    payload: dict[str, Any] = {
        "call_id": call_id,
        "user_id": user_id,
        "phone": phone,
    }
    if transcript_summary:
        payload["transcript_summary"] = transcript_summary
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    if ended_reason:
        payload["ended_reason"] = ended_reason
    await _post(f"{base}/voice/post-call", payload, action="post_call")


async def _post(url: str, payload: dict[str, Any], action: str) -> None:
    secret = _hook_secret()
    headers = {"content-type": "application/json"}
    if secret:
        headers["authorization"] = f"Bearer {secret}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                log.warning(
                    "brain %s hook %s — %s", action, r.status_code, r.text[:200],
                )
            else:
                log.info("brain %s hook ok (%s)", action, r.status_code)
    except Exception:
        log.exception("brain %s hook failed (non-fatal)", action)
