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
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
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
from backend.db.session import async_session
from backend.dashboard.store import get_latest_manifest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/{user_id}/attention/{attention_id}")
async def attention_detail(user_id: str, attention_id: str) -> JSONResponse:
    """Rich detail view for one attention.

    Powers the bottom-sheet drawer: fetches the attention row, joins to
    its evidence observations, pulls recent ticks, and returns a single
    payload the frontend can render without follow-up calls.

    Scoped to ``user_id`` — refuses to return another user's attention.
    """
    from sqlalchemy import desc as _desc, select as _select

    from db.models import (
        AttentionRow,
        AttentionTickRow,
        Observation,
    )
    from backend.db.session import async_session as _session

    async with _session() as s:
        att = (
            await s.execute(
                _select(AttentionRow)
                .where(AttentionRow.id == attention_id)
                .where(AttentionRow.user_id == user_id)
            )
        ).scalar_one_or_none()
        if att is None:
            raise HTTPException(status_code=404, detail="attention not found")

        ticks = (
            await s.execute(
                _select(AttentionTickRow)
                .where(AttentionTickRow.attention_id == attention_id)
                .order_by(_desc(AttentionTickRow.at))
                .limit(20)
            )
        ).scalars().all()

        payload = dict(att.payload or {})
        spec = payload.get("spec") or {}
        state = payload.get("current_state") or {}
        evidence_ids = state.get("evidence_ids") or []
        evidence: list[dict[str, Any]] = []
        if isinstance(evidence_ids, list) and evidence_ids:
            obs_rows = (
                await s.execute(
                    _select(Observation)
                    .where(Observation.id.in_([str(x) for x in evidence_ids if x]))
                    .order_by(_desc(Observation.event_time))
                )
            ).scalars().all()
            for o in obs_rows:
                evidence.append({
                    "id": o.id,
                    "type": o.type,
                    "fields": dict(o.fields or {}),
                    "raw": o.raw or "",
                    "event_time": o.event_time.isoformat() if o.event_time else None,
                })

    subject = spec.get("subject") if isinstance(spec, dict) else None
    cadence = spec.get("cadence") if isinstance(spec, dict) else None
    surface_policy = spec.get("surface_policy") if isinstance(spec, dict) else None

    # 7-day history for tally cards: sum the relevant numeric field per
    # user-local day. Drives the tiny trend bars in the user-facing sheet.
    history: list[dict[str, Any]] = []
    if att.card == "tally":
        history = await _tally_history(
            user_id=user_id,
            spec=spec if isinstance(spec, dict) else {},
            days=7,
        )

    return JSONResponse(content={
        "id": att.id,
        "user_id": att.user_id,
        "card": att.card,
        "status": att.status,
        "title": spec.get("title") if isinstance(spec, dict) else None,
        "description": spec.get("description") if isinstance(spec, dict) else None,
        "subject": subject if isinstance(subject, dict) else None,
        "cadence": cadence if isinstance(cadence, dict) else None,
        "surface_policy": surface_policy if isinstance(surface_policy, dict) else None,
        "current_state": state,
        "evidence": evidence,
        "ticks": [
            {
                "id": t.id,
                "at": t.at.isoformat() if t.at else None,
                "rendered_markdown": t.rendered_markdown,
                "source_counts": dict(t.source_counts or {}),
            }
            for t in ticks
        ],
        "created_at": att.created_at.isoformat() if att.created_at else None,
        "last_surfaced_at": att.last_surfaced_at.isoformat() if att.last_surfaced_at else None,
        "last_update_at": payload.get("last_update_at"),
        "history": history,
    })


_TALLY_TAG_TO_FIELD = {
    "meal_calories": ("meal", "calories"),
    "meal": ("meal", "calories"),
    "expense": ("expense", "amount"),
    "spend": ("expense", "amount"),
    "sleep_hours": ("sleep", "hours"),
    "sleep": ("sleep", "hours"),
}


async def _tally_history(
    *, user_id: str, spec: dict[str, Any], days: int = 7
) -> list[dict[str, Any]]:
    """Last ``days`` user-local days of summed values for a tally attention.

    Picks the (obs_type, field) pair from the spec's first source tag.
    Returns a list ordered oldest-first with ISO date + summed value +
    contributing count. Fail-soft: missing data returns zero rows for
    that day, never raises."""
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo as _Zone

    sources = spec.get("sources") or []
    tag = ""
    for s in sources:
        params = s.get("params") if isinstance(s, dict) else None
        t = params.get("tag") if isinstance(params, dict) else None
        if t:
            tag = str(t)
            break
    obs_type, field_name = _TALLY_TAG_TO_FIELD.get(tag, ("", ""))
    if not obs_type:
        return []

    # Resolve user timezone for day windowing.
    user_tz = "Asia/Kolkata"
    try:
        async with async_session() as s:
            from db.models import User as _User
            u = (await s.execute(
                select(_User).where(_User.id == user_id)
            )).scalar_one_or_none()
            if u and u.timezone:
                user_tz = u.timezone
    except Exception:
        pass

    try:
        tz = _Zone(user_tz)
    except Exception:
        tz = _Zone("Asia/Kolkata")

    today_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start_local = today_local - _td(days=days - 1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)

    from db.models import Observation as _Obs

    try:
        async with async_session() as s:
            rows = (await s.execute(
                select(_Obs)
                .where(_Obs.user_id == user_id)
                .where(_Obs.type == obs_type)
                .where(_Obs.event_time >= start_utc)
                .order_by(_Obs.event_time.asc())
            )).scalars().all()
    except Exception:
        logger.exception("tally_history: db read failed user=%s", user_id[:8])
        return []

    buckets: dict[str, dict[str, Any]] = {}
    for d in range(days):
        day = (start_local + _td(days=d)).date().isoformat()
        buckets[day] = {"day": day, "value": 0.0, "count": 0}
    for o in rows:
        et = o.event_time
        if et is None:
            continue
        # event_time is naive UTC by convention
        et_utc = et.replace(tzinfo=timezone.utc) if et.tzinfo is None else et
        local = et_utc.astimezone(tz)
        day_key = local.date().isoformat()
        if day_key not in buckets:
            continue
        v = (o.fields or {}).get(field_name)
        if v is None:
            continue
        try:
            buckets[day_key]["value"] += float(v)
            buckets[day_key]["count"] += 1
        except (TypeError, ValueError):
            continue

    return [buckets[(start_local + _td(days=d)).date().isoformat()] for d in range(days)]


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

    # ── Generic verbs landing this turn ───────────────────────────────────
    # Each verb maps to a deterministic backend write. Where a write doesn't
    # cleanly fit existing tools, we degrade to log_observation so the
    # action persists as a structured event the brain can recall later.

    if verb == "log_value":
        action = request.action or {}
        tracker = str(action.get("tracker") or "").strip()
        value = action.get("value")
        unit = action.get("unit")
        if not tracker or value is None:
            raise HTTPException(
                status_code=400,
                detail="action.tracker and action.value are required",
            )
        try:
            value_num = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="value must be numeric")
        result = await _log_observation(
            user_id=user_id,
            obs_type=_observation_type_for_tracker(tracker),
            fields={"value": value_num, "unit": unit, "tracker": tracker},
            raw=f"{value_num}{(' ' + unit) if unit else ''} {tracker}".strip(),
            tags={"source": "dashboard", "verb": "log_value", "tracker": tracker},
        )
        return _ack(verb, message=f"{value_num}{(' ' + unit) if unit else ''} logged on {tracker}.", **result)

    if verb == "quick_log":
        action = request.action or {}
        kind = str(action.get("kind") or "note").strip() or "note"
        payload = action.get("payload")
        text_payload = (
            payload if isinstance(payload, str) else _safe_short_dump(payload)
        )
        result = await _log_observation(
            user_id=user_id,
            obs_type=kind,
            fields={"payload": payload} if isinstance(payload, dict) else {"text": str(payload or "")[:500]},
            raw=str(text_payload)[:500],
            tags={"source": "dashboard", "verb": "quick_log", "kind": kind},
        )
        return _ack(verb, message=f"logged. ({kind})", **result)

    if verb == "complete_pick":
        action = request.action or {}
        pick_id = str(action.get("pickId") or action.get("pick_id") or "").strip()
        if not pick_id:
            raise HTTPException(status_code=400, detail="action.pickId is required")
        result = await _log_observation(
            user_id=user_id,
            obs_type="pick",
            fields={"pick_id": pick_id, "outcome": "kept"},
            raw=f"pick {pick_id} kept",
            tags={"source": "dashboard", "verb": "complete_pick"},
        )
        return _ack(verb, message="kept. nice.", pick_id=pick_id, **result)

    if verb == "decide_option":
        action = request.action or {}
        decision_id = str(action.get("decisionId") or action.get("decision_id") or "").strip()
        option_id = str(action.get("optionId") or action.get("option_id") or "").strip()
        if not decision_id or not option_id:
            raise HTTPException(
                status_code=400,
                detail="action.decisionId and action.optionId are required",
            )
        result = await _log_observation(
            user_id=user_id,
            obs_type="decision",
            fields={"decision_id": decision_id, "option_id": option_id},
            raw=f"decided {option_id} for {decision_id}",
            tags={"source": "dashboard", "verb": "decide_option"},
        )
        return _ack(
            verb,
            message="noted. picked the same.",
            decision_id=decision_id,
            option_id=option_id,
            **result,
        )

    if verb == "snooze_reminder":
        action = request.action or {}
        reminder_id = str(
            action.get("reminderId") or action.get("reminder_id") or ""
        ).strip()
        until = str(action.get("until") or "").strip()
        if not reminder_id or not until:
            raise HTTPException(
                status_code=400,
                detail="action.reminderId and action.until are required",
            )
        # First cut: log the snooze intent as an observation. The schedule
        # worker / attention store will pick it up via the next sweep. A
        # full implementation would re-anchor the DonnaSchedule row.
        result = await _log_observation(
            user_id=user_id,
            obs_type="reminder_snoozed",
            fields={"reminder_id": reminder_id, "until": until},
            raw=f"snoozed {reminder_id} until {until}",
            tags={"source": "dashboard", "verb": "snooze_reminder"},
        )
        return _ack(verb, message=f"snoozed until {until}.", reminder_id=reminder_id, **result)

    if verb == "start_tracker":
        action = request.action or {}
        name = str(action.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="action.name is required")
        try:
            from donna.attention.tools import create_attention as _create

            create_result = await _create(
                f"track my {name}", user_id, auto_live=True
            )
            return _ack(
                verb,
                message=f"{name} tracker on. tell me when you log something.",
                attention_id=str(create_result.attention.id),
                reused=create_result.reused,
            )
        except Exception as e:
            logger.exception("start_tracker failed user=%s name=%s", user_id, name)
            raise HTTPException(status_code=500, detail=str(e)[:300])

    if verb == "accept_draft":
        action = request.action or {}
        draft_id = str(action.get("draftId") or action.get("draft_id") or "").strip()
        if not draft_id:
            raise HTTPException(status_code=400, detail="action.draftId is required")
        # Mark the pending note delivered. The brain's next reactive turn
        # will see it cleared and the user has confirmed acceptance.
        try:
            from proactive.dispatcher import clear_pending_note

            cleared = await clear_pending_note(draft_id, reason="delivered")
            return _ack(verb, message="sending it.", draft_id=draft_id, cleared=cleared)
        except Exception:
            logger.exception("accept_draft: clear_pending_note failed")
            return _ack(verb, message="sending it.", draft_id=draft_id, cleared=False)

    if verb == "connect_integration":
        action = request.action or {}
        provider = str(action.get("provider") or "").strip()
        if not provider:
            raise HTTPException(
                status_code=400, detail="action.provider is required"
            )
        # The dashboard never holds OAuth state itself — it nudges the
        # brain to start the flow. Log the intent as a quick_log so the
        # brain can ack and kick off connect on the next reactive turn.
        result = await _log_observation(
            user_id=user_id,
            obs_type="connect_integration_request",
            fields={"provider": provider},
            raw=f"requested connect: {provider}",
            tags={"source": "dashboard", "verb": "connect_integration"},
        )
        return _ack(
            verb,
            message=f"pulling {provider} now. give me a minute.",
            provider=provider,
            **result,
        )

    if verb == "reply_chip":
        action = request.action or {}
        intent = str(action.get("intent") or "").strip()
        if not intent:
            raise HTTPException(
                status_code=400, detail="action.intent is required"
            )
        result = await _log_observation(
            user_id=user_id,
            obs_type="reply_chip",
            fields={"intent": intent},
            raw=f"reply chip: {intent}",
            tags={"source": "dashboard", "verb": "reply_chip"},
        )
        return _ack(
            verb,
            message=f"drafting a reply about {intent}.",
            intent=intent,
            **result,
        )

    # "Open" verbs are deep-view navigation hints. Today they no-op but
    # still ack so the dashboard can surface the feedback and a future
    # iteration can wire the brain side.
    if verb in {"open_relationship", "open_news", "open_tracker"}:
        action = request.action or {}
        return _ack(
            verb,
            message=_open_message_for(verb, action),
            **{k: action.get(k) for k in ("personId", "newsId", "tracker") if action.get(k)},
        )

    raise HTTPException(status_code=501, detail=f"verb '{verb}' not implemented")


# ── Helpers used by the verb dispatch ───────────────────────────────────────


def _ack(verb: str, *, message: str, **extras: Any) -> JSONResponse:
    """Standard 200 envelope returned to the dashboard. ``message`` is the
    Donna-voice ack the renderer surfaces as a transient toast — the same
    voice the user would see in WhatsApp."""
    payload: dict[str, Any] = {"ok": True, "verb": verb, "message": message}
    for k, v in extras.items():
        if v is not None:
            payload[k] = v
    return JSONResponse(content=payload)


def _safe_short_dump(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        import json as _json

        return _json.dumps(value, default=str)[:500]
    except Exception:
        return str(value)[:500]


def _observation_type_for_tracker(name: str) -> str:
    """Map a tracker name to an observation type. Best-effort; falls back
    to ``"tracker"`` so the row is still queryable later."""
    n = name.lower().strip()
    if any(k in n for k in ("calorie", "meal", "food")):
        return "meal"
    if any(k in n for k in ("sleep", "rest", "bedtime")):
        return "sleep"
    if any(k in n for k in ("water", "hydrat")):
        return "habit"
    if any(k in n for k in ("spend", "expense", "money")):
        return "expense"
    if any(k in n for k in ("mood", "feel")):
        return "mood"
    if any(k in n for k in ("workout", "run", "lift", "exercise")):
        return "exercise"
    return "tracker"


def _open_message_for(verb: str, action: dict[str, Any]) -> str:
    if verb == "open_relationship":
        person = action.get("personId") or "them"
        return f"pulling up what i have on {person}."
    if verb == "open_news":
        return "opening."
    if verb == "open_tracker":
        return f"{action.get('tracker') or 'tracker'} — full sheet coming up."
    return "done."


async def _log_observation(
    *,
    user_id: str,
    obs_type: str,
    fields: dict[str, Any],
    raw: str,
    tags: dict[str, Any] | None = None,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Wraps the existing log_observation tool, returning the new id +
    a degraded-state hint when the write fails. Never raises — the
    action ack still lands with ``ok=True`` because the user's tap was
    captured even if downstream write failed."""
    try:
        from backend.memory.tools.log_observation import log_observation as _log

        result = await _log(
            user_id=user_id,
            type=obs_type,
            fields=dict(fields or {}),
            tags=dict(tags or {}),
            raw=raw,
            confidence=confidence,
        )
        if isinstance(result, dict):
            data = result.get("data") or {}
            if isinstance(data, dict) and data.get("id"):
                return {"observation_id": str(data["id"])}
        return {}
    except Exception:
        logger.exception("dashboard.action: log_observation failed")
        return {"degraded": "observation_write_failed"}


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
