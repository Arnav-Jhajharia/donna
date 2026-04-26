"""Dashboard HTTP surface.

GET  /api/dashboard/{user_id}/manifest        — the latest plan, polled by the renderer.
POST /api/dashboard/{user_id}/action          — execute an ActionVerb the user tapped.

The renderer polls the manifest every ~20s and falls back to local
fixtures when the response is 404, so a missing row is not an error
path.

The action endpoint is the single seam through which the dashboard
mutates server-side state. Today it dispatches two verbs:

- ``accept_attention``  — flip an OFFERED attention to LIVE, materialize
  the appropriate ``DonnaInstance`` (for TALLY/EVENT_STREAM cards), and
  trigger a dashboard recompose.
- ``dismiss_attention`` — flip an OFFERED attention to REJECTED so it
  stops showing up, with a cooldown enforced by the proposer layer.

Unknown verbs return 501. We grow the dispatch as new verbs land.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.dashboard.actions import (
    AcceptResult,
    accept_offered_attention,
    dismiss_offered_attention,
    mark_reminder_done,
)
from backend.dashboard.manifest_events import subscribe as subscribe_manifest_changes
from backend.dashboard.state_snapshot import gather_state
from backend.dashboard.store import get_latest_manifest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/{user_id}/manifest")
async def get_manifest(user_id: str) -> JSONResponse:
    plan = await get_latest_manifest(user_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="no manifest yet")
    return JSONResponse(content=plan, headers={"cache-control": "no-store"})


@router.get("/{user_id}/events")
async def manifest_events(user_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events stream of manifest changes for ``user_id``.

    Emits a ``data: manifest_changed`` line every time
    ``upsert_manifest`` lands a new plan. Frontend subscribes via
    ``new EventSource(...)`` and re-fetches the manifest endpoint on
    each event. Sends a keep-alive comment every 25s so proxies don't
    close idle connections.
    """

    async def event_stream():
        # Welcome event so the client knows the stream is alive.
        yield "event: ready\ndata: subscribed\n\n"
        keepalive_every_s = 25.0
        async for kind in _wrap_with_keepalive(
            subscribe_manifest_changes(user_id),
            request,
            keepalive_every_s,
        ):
            if kind is None:
                # heartbeat
                yield ": keep-alive\n\n"
            else:
                yield f"data: {kind}\n\n"

    headers = {
        "cache-control": "no-store",
        "x-accel-buffering": "no",  # prevent nginx buffering if proxied
        "connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


async def _wrap_with_keepalive(source, request: Request, every_s: float):
    """Yield events from ``source``; insert ``None`` heartbeats every
    ``every_s`` seconds; stop when the client disconnects.
    """
    iterator = source.__aiter__()
    next_event_task: asyncio.Task | None = None
    try:
        while True:
            if await request.is_disconnected():
                return
            if next_event_task is None:
                next_event_task = asyncio.create_task(iterator.__anext__())
            done, _ = await asyncio.wait(
                {next_event_task}, timeout=every_s
            )
            if not done:
                yield None  # heartbeat
                continue
            try:
                kind = next_event_task.result()
            except StopAsyncIteration:
                return
            finally:
                next_event_task = None
            yield kind
    finally:
        if next_event_task is not None and not next_event_task.done():
            next_event_task.cancel()


@router.get("/{user_id}/state")
async def get_state(user_id: str) -> JSONResponse:
    """One-shot state snapshot for /observe.

    Returns user / living_profile / attentions / instances / schedules /
    observations / open_loops / chat. Each subsection is fault-tolerant —
    a partial result still renders rather than 500ing.
    """
    snapshot = await gather_state(user_id)
    if snapshot.get("user") is None:
        raise HTTPException(status_code=404, detail="user not found")
    return JSONResponse(content=snapshot, headers={"cache-control": "no-store"})


class ActionRequest(BaseModel):
    """Wraps a single ActionVerb from the dashboard.

    Pydantic does not parse the ActionVerb discriminated union directly
    here because that schema lives in ``backend.dashboard.schema`` and
    we want this surface to be lenient (forwards-compatible with verbs
    only the renderer knows about). We pull ``v`` and the verb-specific
    fields out by hand below.
    """

    action: dict[str, Any] = Field(default_factory=dict)


@router.post("/{user_id}/action")
async def execute_action(user_id: str, request: ActionRequest) -> JSONResponse:
    verb = (request.action or {}).get("v")
    if not verb:
        raise HTTPException(status_code=400, detail="action.v is required")

    if verb == "accept_attention":
        attention_id = _attention_id_from(request.action)
        if not attention_id:
            raise HTTPException(
                status_code=400, detail="action.attentionId is required"
            )
        result = await accept_offered_attention(
            user_id=user_id, attention_id=attention_id
        )
        return _json_for_accept(result)

    if verb == "dismiss_attention":
        attention_id = _attention_id_from(request.action)
        if not attention_id:
            raise HTTPException(
                status_code=400, detail="action.attentionId is required"
            )
        ok = await dismiss_offered_attention(
            user_id=user_id, attention_id=attention_id
        )
        return JSONResponse(
            content={"ok": ok, "verb": verb, "attention_id": attention_id},
        )

    if verb == "mark_reminder_done":
        reminder_id = _reminder_id_from(request.action)
        if not reminder_id:
            raise HTTPException(
                status_code=400, detail="action.reminderId is required"
            )
        ok, error = await mark_reminder_done(
            user_id=user_id, reminder_id=reminder_id
        )
        payload = {"ok": ok, "verb": verb, "reminder_id": reminder_id}
        if not ok and error:
            payload["error"] = error
        return JSONResponse(
            content=payload, status_code=200 if ok else 409
        )

    raise HTTPException(status_code=501, detail=f"verb '{verb}' not implemented")


def _attention_id_from(action: dict[str, Any]) -> str:
    # The TS contract uses ``attentionId``; the Python model uses
    # ``attention_id``. Accept either to keep this surface forgiving.
    raw = action.get("attentionId") or action.get("attention_id") or ""
    return str(raw).strip()


def _reminder_id_from(action: dict[str, Any]) -> str:
    raw = action.get("reminderId") or action.get("reminder_id") or ""
    return str(raw).strip()


def _json_for_accept(result: AcceptResult) -> JSONResponse:
    payload = {
        "ok": result.ok,
        "verb": "accept_attention",
        "attention_id": result.attention_id,
        "status": result.status,
        "instance_id": result.instance_id,
        "instance_created": result.instance_created,
        "recomposed": result.recomposed,
    }
    if not result.ok and result.error:
        payload["error"] = result.error
    status_code = 200 if result.ok else 409
    return JSONResponse(content=payload, status_code=status_code)
