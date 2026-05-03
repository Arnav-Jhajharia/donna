"""Admin observability surface — every interesting thing about a user
in one place. Read-only by design; the Next.js /admin pages drive it.

Auth: HTTP Basic against ADMIN_USER/ADMIN_PASSWORD env vars. The Next.js
edge middleware enforces the same gate before the request even reaches
us, but we re-check here so direct ``curl`` access doesn't leak data.

Endpoints (all GET):
  /api/admin/users                       — user list with last-active + counts
  /api/admin/{uid}/overview              — one-shot snapshot for dashboard cards
  /api/admin/{uid}/integrations          — composio truth + local DB rows
  /api/admin/{uid}/proactive             — proactive_pings (sent + suppressed)
  /api/admin/{uid}/tools                 — recent tool.call events from events.jsonl
  /api/admin/{uid}/turns                 — chat turns with system_prompt + cost
  /api/admin/{uid}/memory/open_loops     — open_loops table rows
  /api/admin/{uid}/memory/observations   — observations table rows
  /api/admin/{uid}/memory/user_facts     — user_facts table rows
  /api/admin/{uid}/memory/biography      — living_profile.biography JSON
  /api/admin/{uid}/memory/profile        — full living_profile JSON dump
  /api/admin/{uid}/memory/supermemory    — supermemory chunks for the user
  /api/admin/{uid}/memory/graphiti       — graphiti entities + edges (if available)
  /api/admin/{uid}/email                 — paginated email_messages
  /api/admin/{uid}/calendar              — calendar_entries
  /api/admin/{uid}/attentions            — attentions (any state)
  /api/admin/{uid}/chat                  — chat_messages tail
  /api/admin/{uid}/raw                   — raw User row dump
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import desc, func, select

from backend.db.session import async_session
from db.models import (
    AttentionRow,
    AttentionTickRow,
    CalendarEntry,
    ChatMessage,
    DonnaSchedule,
    EmailMessage,
    Integration,
    Observation,
    ObsEvent,
    OpenLoop,
    ProactivePing,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])
_basic = HTTPBasic()


# ── Auth ────────────────────────────────────────────────────────────────────


def _require_admin(
    creds: HTTPBasicCredentials = Depends(_basic),
) -> str:
    """Constant-time check against env-var credentials. ADMIN_USER defaults
    to 'admin' for convenience; ADMIN_PASSWORD must be set or the route
    returns 503 (refuse to run unauthenticated)."""
    expected_user = os.environ.get("ADMIN_USER", "admin")
    expected_pw = os.environ.get("ADMIN_PASSWORD", "")
    if not expected_pw:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASSWORD not configured",
        )
    user_ok = secrets.compare_digest(creds.username, expected_user)
    pw_ok = secrets.compare_digest(creds.password, expected_pw)
    if not (user_ok and pw_ok):
        raise HTTPException(
            status_code=401,
            detail="bad admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


# ── Helpers ─────────────────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


_EVENTS_LOG_PATH = Path(".donna") / "events.jsonl"


def _read_events_for_user(
    user_id: str, *, limit: int = 200, kinds: set[str] | None = None
) -> list[dict[str, Any]]:
    """Tail-read events.jsonl, returning the last N matching lines for the
    user. Cheap because the file is line-delimited; we read from the end
    in chunks to avoid loading 100MB+ of history."""
    if not _EVENTS_LOG_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with _EVENTS_LOG_PATH.open("rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            chunk = 256 * 1024
            buf = b""
            while file_size > 0 and len(out) < limit:
                read_size = min(chunk, file_size)
                file_size -= read_size
                f.seek(file_size)
                buf = f.read(read_size) + buf
                lines = buf.split(b"\n")
                # The first chunk we read may have a partial line at the
                # start; keep it for the next iteration.
                buf = lines[0] if file_size > 0 else b""
                # Walk newest -> oldest
                for raw in reversed(lines[1:] if file_size > 0 else lines):
                    if not raw.strip():
                        continue
                    try:
                        ev = json.loads(raw.decode("utf-8"))
                    except Exception:
                        continue
                    if ev.get("user_id") != user_id:
                        continue
                    if kinds and ev.get("event") not in kinds:
                        continue
                    out.append(ev)
                    if len(out) >= limit:
                        break
    except Exception:
        logger.exception("admin: events.jsonl tail-read failed")
    return out


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/events")
async def events_stream(
    _admin: str = Depends(_require_admin),
    limit: int = Query(2000, ge=1, le=10000),
    user_id: str | None = Query(None),
):
    """DB-backed event stream for the /observe dashboard.

    Returns the most recent N events from ``obs_events`` (the table the
    brain writes to via ``donna_runtime.obs_sink``). Each row is flattened
    back into the same shape the legacy ``.donna/events.jsonl`` produced
    so the dashboard's existing parsing logic doesn't need to change.

    ``limit`` defaults high — /observe groups events into turns and trims
    by turn count, so it needs the raw event tail. Cap is 10k.
    """
    async with async_session() as s:
        stmt = select(ObsEvent).order_by(desc(ObsEvent.ts)).limit(limit)
        if user_id:
            stmt = stmt.where(ObsEvent.user_id == user_id)
        rows = (await s.execute(stmt)).scalars().all()

    events: list[dict[str, Any]] = []
    for r in rows:
        # Reconstruct the JSONL line shape: payload IS the full event
        # (we stored it that way). Replay it untouched so the existing
        # /observe parser keeps working.
        events.append(r.payload if isinstance(r.payload, dict) else {})

    # The legacy file was newest-last (append-only); the dashboard reads
    # newest-first behavior internally, but the existing groupTurns() in
    # the Next.js layer iterates in encounter order. Ship oldest-first to
    # match the file's iteration semantics.
    events.reverse()

    return {
        "events": events,
        "count": len(events),
        "source": "db",
    }


@router.get("/users")
async def list_users(
    _admin: str = Depends(_require_admin),
    limit: int = Query(50, ge=1, le=500),
):
    """Quick list of users with the per-user counts most useful for triage:
    integrations, recent pings, recent emails, last activity."""
    async with async_session() as s:
        users = (
            await s.execute(
                select(User).order_by(desc(User.last_active_at)).limit(limit)
            )
        ).scalars().all()
        rows = []
        for u in users:
            integ_count = (await s.execute(
                select(func.count(Integration.id)).where(
                    Integration.user_id == u.id
                )
            )).scalar() or 0
            ping_count = (await s.execute(
                select(func.count(ProactivePing.id)).where(
                    ProactivePing.user_id == u.id
                )
            )).scalar() or 0
            email_count = (await s.execute(
                select(func.count(EmailMessage.id)).where(
                    EmailMessage.user_id == u.id
                )
            )).scalar() or 0
            chat_count = (await s.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.user_id == u.id
                )
            )).scalar() or 0
            rows.append({
                "id": u.id,
                "phone": u.phone,
                "name": u.name,
                "timezone": u.timezone,
                "is_sandbox": u.is_sandbox,
                "created_at": _iso(u.created_at),
                "last_active_at": _iso(u.last_active_at),
                "integrations": integ_count,
                "proactive_pings": ping_count,
                "emails": email_count,
                "chat_messages": chat_count,
            })
    return {"users": rows}


@router.get("/{user_id}/overview")
async def overview(
    user_id: str, _admin: str = Depends(_require_admin)
):
    """One-shot snapshot for the overview cards: integrations, bootstrap
    status, biography head, ping counts, ingest counts, recent activity."""
    async with async_session() as s:
        u = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="user not found")
        prof = u.living_profile or {}
        bio = prof.get("biography") or {}
        bootstrap_runs = prof.get("bootstrap_runs") or {}
        notified = prof.get("notified_integrations") or {}
        integrations = (await s.execute(
            select(Integration).where(Integration.user_id == user_id)
        )).scalars().all()
        email_total = (await s.execute(
            select(func.count(EmailMessage.id)).where(
                EmailMessage.user_id == user_id
            )
        )).scalar() or 0
        email_with_body = (await s.execute(
            select(func.count(EmailMessage.id))
            .where(EmailMessage.user_id == user_id)
            .where(EmailMessage.body_stored.is_(True))
        )).scalar() or 0
        cal_total = (await s.execute(
            select(func.count(CalendarEntry.id)).where(
                CalendarEntry.user_id == user_id
            )
        )).scalar() or 0
        ping_total = (await s.execute(
            select(func.count(ProactivePing.id)).where(
                ProactivePing.user_id == user_id
            )
        )).scalar() or 0
        ping_sent = (await s.execute(
            select(func.count(ProactivePing.id))
            .where(ProactivePing.user_id == user_id)
            .where(ProactivePing.suppressed_reason.is_(None))
        )).scalar() or 0
        chat_total = (await s.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.user_id == user_id
            )
        )).scalar() or 0
        observations_total = (await s.execute(
            select(func.count(Observation.id)).where(
                Observation.user_id == user_id
            )
        )).scalar() or 0
        loops_open = (await s.execute(
            select(func.count(OpenLoop.id))
            .where(OpenLoop.user_id == user_id)
            .where(OpenLoop.status == "active")
        )).scalar() or 0
        loops_total = (await s.execute(
            select(func.count(OpenLoop.id)).where(
                OpenLoop.user_id == user_id
            )
        )).scalar() or 0

    return {
        "user": {
            "id": u.id,
            "phone": u.phone,
            "name": u.name,
            "timezone": u.timezone,
            "wake_time": u.wake_time,
            "sleep_time": u.sleep_time,
            "is_sandbox": u.is_sandbox,
            "created_at": _iso(u.created_at),
            "last_active_at": _iso(u.last_active_at),
        },
        "integrations": [
            {
                "provider": r.provider,
                "product": r.product,
                "status": r.status,
                "composio_connection_id": r.composio_connection_id,
                "connected_at": _iso(r.connected_at),
                "last_synced_at": _iso(r.last_synced_at),
                "last_error": r.last_error,
            }
            for r in integrations
        ],
        "bootstrap_runs": bootstrap_runs,
        "notified_integrations": notified,
        "biography_summary": {
            "keys": list(bio.keys()),
            "overview": (bio.get("overview") or "")[:600],
            "evidence_window": bio.get("evidence_window"),
            "last_bootstrapped_at": bio.get("last_bootstrapped_at"),
        },
        "counts": {
            "emails_total": email_total,
            "emails_with_body": email_with_body,
            "calendar_entries": cal_total,
            "proactive_pings_total": ping_total,
            "proactive_pings_sent": ping_sent,
            "chat_messages": chat_total,
            "observations": observations_total,
            "open_loops_active": loops_open,
            "open_loops_total": loops_total,
        },
    }


@router.get("/{user_id}/integrations")
async def integrations_full(
    user_id: str, _admin: str = Depends(_require_admin)
):
    """Local DB rows joined with Composio truth (live API call). Lets you
    spot drift at a glance."""
    async with async_session() as s:
        local = (await s.execute(
            select(Integration).where(Integration.user_id == user_id)
        )).scalars().all()
    composio_rows = []
    try:
        from backend.integrations import composio_meta
        c = composio_meta._composio()
        listing = c.connected_accounts.list(user_ids=[user_id])
        items = (
            listing.items if hasattr(listing, "items") else list(listing)
        )
        for ca in items:
            composio_rows.append({
                "id": getattr(ca, "id", None),
                "status": getattr(ca, "status", None),
                "toolkit": getattr(getattr(ca, "toolkit", None), "slug", None),
                "created_at": str(
                    getattr(ca, "created_at", None)
                    or getattr(ca, "createdAt", None)
                    or ""
                ),
            })
    except Exception as e:
        logger.exception("admin: composio probe failed")
        composio_rows = [{"error": str(e)[:300]}]
    return {
        "local": [
            {
                "provider": r.provider,
                "product": r.product,
                "status": r.status,
                "composio_connection_id": r.composio_connection_id,
                "connected_at": _iso(r.connected_at),
                "last_synced_at": _iso(r.last_synced_at),
                "redirect_url": r.redirect_url,
                "redirect_url_issued_at": _iso(r.redirect_url_issued_at),
                "last_error": r.last_error,
                "updated_at": _iso(r.updated_at),
            }
            for r in local
        ],
        "composio": composio_rows,
    }


@router.get("/{user_id}/proactive")
async def proactive_pings(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(100, ge=1, le=500),
):
    """All proactive pings — sent + suppressed — newest first."""
    async with async_session() as s:
        rows = (await s.execute(
            select(ProactivePing)
            .where(ProactivePing.user_id == user_id)
            .order_by(desc(ProactivePing.fired_at))
            .limit(limit)
        )).scalars().all()
        sent = (await s.execute(
            select(func.count(ProactivePing.id))
            .where(ProactivePing.user_id == user_id)
            .where(ProactivePing.suppressed_reason.is_(None))
        )).scalar() or 0
        suppressed = (await s.execute(
            select(func.count(ProactivePing.id))
            .where(ProactivePing.user_id == user_id)
            .where(ProactivePing.suppressed_reason.is_not(None))
        )).scalar() or 0
    return {
        "totals": {"sent": sent, "suppressed": suppressed},
        "pings": [
            {
                "id": r.id,
                "source": r.source,
                "message_ref": r.message_ref,
                "topic_key": getattr(r, "topic_key", None),
                "fired_at": _iso(r.fired_at),
                "suppressed_reason": r.suppressed_reason,
                "sent": r.suppressed_reason is None,
            }
            for r in rows
        ],
    }


@router.get("/{user_id}/tools")
async def tool_calls(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(150, ge=1, le=500),
):
    """Recent tool.call + memory.op + hook.deny + image.generated +
    turn.start/end events for the user, with full input/output previews
    where available. Sourced from .donna/events.jsonl."""
    kinds = {
        "tool.call",
        "memory.op",
        "hook.deny",
        "image.generated",
        "turn.start",
        "turn.end",
    }
    events = _read_events_for_user(user_id, limit=limit, kinds=kinds)
    return {"events": events}


@router.get("/{user_id}/turns")
async def turn_history(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(20, ge=1, le=100),
):
    """Per-turn summary with system_prompt snapshot + tool list + cost."""
    snaps = _read_events_for_user(
        user_id, limit=limit * 4, kinds={"prompt.snapshot", "turn.end"}
    )
    by_turn: dict[str, dict[str, Any]] = {}
    for ev in snaps:
        tid = ev.get("turn_id")
        if not tid:
            continue
        bucket = by_turn.setdefault(tid, {"turn_id": tid})
        if ev.get("event") == "prompt.snapshot":
            bucket["system_prompt_head"] = (
                (ev.get("system_prompt") or "")[:1500]
            )
            bucket["snapshot_ts"] = ev.get("ts")
        elif ev.get("event") == "turn.end":
            bucket["duration_ms"] = ev.get("duration_ms")
            bucket["num_turns"] = ev.get("num_turns")
            bucket["total_cost_usd"] = ev.get("total_cost_usd")
            bucket["tools"] = ev.get("tools")
            bucket["terminal_tool"] = ev.get("terminal_tool")
            bucket["session_id"] = ev.get("session_id")
            bucket["end_ts"] = ev.get("ts")
            bucket["cache_creation"] = ev.get("cache_creation_input_tokens")
            bucket["cache_read"] = ev.get("cache_read_input_tokens")
    turns = sorted(
        by_turn.values(),
        key=lambda t: t.get("end_ts") or t.get("snapshot_ts") or "",
        reverse=True,
    )[:limit]
    return {"turns": turns}


@router.get("/{user_id}/memory/open_loops")
async def memory_open_loops(
    user_id: str, _admin: str = Depends(_require_admin)
):
    async with async_session() as s:
        rows = (await s.execute(
            select(OpenLoop)
            .where(OpenLoop.user_id == user_id)
            .order_by(desc(OpenLoop.created_at))
        )).scalars().all()
    # OpenLoop columns: id, user_id, content, source_message, created_at,
    # status, resolved_at, due_at — no updated_at column.
    return {"open_loops": [
        {
            "id": r.id,
            "content": r.content,
            "source_message": r.source_message,
            "status": r.status,
            "due_at": _iso(getattr(r, "due_at", None)),
            "resolved_at": _iso(getattr(r, "resolved_at", None)),
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]}


@router.get("/{user_id}/memory/observations")
async def memory_observations(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(200, ge=1, le=1000),
):
    async with async_session() as s:
        rows = (await s.execute(
            select(Observation)
            .where(Observation.user_id == user_id)
            .order_by(desc(Observation.event_time))
            .limit(limit)
        )).scalars().all()
    return {"observations": [
        {
            "id": r.id,
            "type": r.type,
            "fields": r.fields,
            "tags": r.tags,
            "raw": r.raw,
            "confidence": r.confidence,
            "event_time": _iso(r.event_time),
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]}


@router.get("/{user_id}/memory/biography")
async def memory_biography(
    user_id: str, _admin: str = Depends(_require_admin)
):
    async with async_session() as s:
        u = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="user not found")
    return {"biography": (u.living_profile or {}).get("biography") or {}}


@router.get("/{user_id}/memory/profile")
async def memory_profile(
    user_id: str, _admin: str = Depends(_require_admin)
):
    """Full living_profile JSONB — biography + bootstrap_runs +
    notified_integrations + everything the synthesis layers wrote."""
    async with async_session() as s:
        u = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="user not found")
    return {"living_profile": u.living_profile or {}}


@router.get("/{user_id}/memory/user_facts")
async def memory_user_facts(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(500, ge=1, le=2000),
):
    """Bi-temporal facts table — what we believe about the user, with
    valid-time + recorded-time + supersede chain. Newest first."""
    from db.models import Fact

    async with async_session() as s:
        rows = (await s.execute(
            select(Fact)
            .where(Fact.user_id == user_id)
            .where(Fact.t_recorded_to.is_(None))  # currently-believed only
            .order_by(desc(Fact.created_at))
            .limit(limit)
        )).scalars().all()
    return {"facts": [
        {
            "id": r.id,
            "subject": r.subject,
            "predicate": r.predicate,
            "object": r.object,
            "object_json": r.object_json,
            "confidence": r.confidence,
            "source": r.source,
            "t_valid_from": _iso(r.t_valid_from),
            "t_valid_to": _iso(r.t_valid_to),
            "t_recorded_from": _iso(r.t_recorded_from),
            "superseded_by": r.superseded_by,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]}


@router.get("/{user_id}/memory/supermemory")
async def memory_supermemory(
    user_id: str,
    _admin: str = Depends(_require_admin),
    query: str = Query("", description="Optional substring to search for"),
    limit: int = Query(20, ge=1, le=100),
):
    """Surfaces what the unified recall pipeline would see for this user
    via Supermemory's hybrid memory + document-chunk indexes. Two
    parallel queries — episodic memory (search_with_graph) and document
    chunks (search_document_chunks)."""
    try:
        from backend.memory.clients.supermemory import get_memory_client
    except Exception as e:
        return {
            "memories": [],
            "chunks": [],
            "error": f"client import failed: {e}",
        }
    client = get_memory_client()
    if not getattr(client, "available", True) is True and getattr(
        client, "available", True
    ) is False:
        return {
            "memories": [],
            "chunks": [],
            "error": "supermemory not configured (SUPERMEMORY_API_KEY missing)",
        }
    q = query or "donna"
    memories: list[dict] = []
    chunks: list[dict] = []
    err: str | None = None
    try:
        mem_results = await client.search_with_graph(
            user_id=user_id, query=q, limit=limit
        )
        memories = [
            {
                "id": m.id,
                "content": m.content[:1000],
                "score": m.score,
                "updated_at": m.updated_at,
                "metadata": m.metadata,
                "relations": m.relations[:5],
            }
            for m in mem_results
        ]
    except Exception as e:
        err = f"search_with_graph: {str(e)[:200]}"
    try:
        chunk_results = await client.search_document_chunks(
            user_id=user_id, query=q, limit=limit
        )
        chunks = [
            {
                "content": c.content[:1000],
                "score": c.score,
                "doc_id": c.doc_id,
                "metadata": c.metadata,
            }
            for c in chunk_results
        ]
    except Exception as e:
        err = (err + " | " if err else "") + f"chunks: {str(e)[:200]}"
    return {
        "memories": memories,
        "chunks": chunks,
        "query": q,
        "error": err,
    }


@router.get("/{user_id}/memory/graphiti")
async def memory_graphiti(
    user_id: str,
    _admin: str = Depends(_require_admin),
    query: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    """Graphiti facts — relationships + episodes the entity-extraction
    pipeline pulled out of the user's stream. Uses ``search_facts`` from
    backend.memory.clients.graphiti."""
    try:
        from backend.memory.clients.graphiti import search_facts
    except Exception as e:
        return {"facts": [], "error": f"client import failed: {e}"}
    q = query or "donna"
    try:
        facts = await search_facts(user_id=user_id, query=q, limit=limit)
    except Exception as e:
        return {"facts": [], "error": str(e)[:300]}
    return {"facts": facts or [], "query": q}


@router.get("/{user_id}/email")
async def email_messages(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(50, ge=1, le=500),
    important_only: bool = False,
):
    async with async_session() as s:
        stmt = (
            select(EmailMessage)
            .where(EmailMessage.user_id == user_id)
            .order_by(desc(EmailMessage.internal_date))
            .limit(limit)
        )
        if important_only:
            stmt = stmt.where(EmailMessage.is_important.is_(True))
        rows = (await s.execute(stmt)).scalars().all()
    return {"emails": [
        {
            "id": r.id,
            "gmail_message_id": r.gmail_message_id,
            "thread_id": r.thread_id,
            "from_address": r.from_address,
            "from_name": r.from_name,
            "to_addresses": r.to_addresses,
            "subject": r.subject,
            "snippet": r.snippet,
            "body_text": (r.body_text or "")[:3000],
            "labels": r.labels,
            "is_important": r.is_important,
            "is_starred": r.is_starred,
            "is_sent": r.is_sent,
            "ingest_depth": r.ingest_depth,
            "internal_date": _iso(r.internal_date),
            "ingested_at": _iso(r.ingested_at),
        }
        for r in rows
    ]}


@router.get("/{user_id}/calendar")
async def calendar_entries(
    user_id: str, _admin: str = Depends(_require_admin)
):
    async with async_session() as s:
        rows = (await s.execute(
            select(CalendarEntry)
            .where(CalendarEntry.user_id == user_id)
            .order_by(CalendarEntry.start_time.asc())
        )).scalars().all()
    return {"events": [
        {c.name: (
            _iso(getattr(r, c.name))
            if isinstance(getattr(r, c.name, None), datetime)
            else getattr(r, c.name, None)
        ) for c in CalendarEntry.__table__.columns}
        for r in rows
    ]}


@router.get("/{user_id}/attentions")
async def attentions(
    user_id: str, _admin: str = Depends(_require_admin)
):
    """Best-effort attentions probe (storage backend name varies)."""
    try:
        from donna.attention.postgres_store import PostgresAttentionStore  # type: ignore

        store = PostgresAttentionStore()
        rows = await store.list(user_id=user_id)  # type: ignore
        out = []
        for a in rows:
            out.append({
                "id": getattr(a, "id", None),
                "title": getattr(getattr(a, "spec", None), "title", None),
                "card_type": (
                    getattr(getattr(a, "spec", None), "card", None).value
                    if getattr(getattr(a, "spec", None), "card", None)
                    else None
                ),
                "state": getattr(a, "state", None),
                "created_at": _iso(getattr(a, "created_at", None)),
                "raw": str(a)[:500],
            })
        return {"attentions": out}
    except Exception as e:
        logger.warning("admin: attentions probe failed: %s", e)
        return {"attentions": [], "error": str(e)[:300]}


@router.get("/{user_id}/chat")
async def chat_history(
    user_id: str,
    _admin: str = Depends(_require_admin),
    limit: int = Query(100, ge=1, le=500),
):
    async with async_session() as s:
        rows = (await s.execute(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(limit)
        )).scalars().all()
    return {"messages": [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "wa_message_id": r.wa_message_id,
            "is_proactive": r.is_proactive,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]}


@router.get("/{user_id}/raw")
async def raw_user(
    user_id: str, _admin: str = Depends(_require_admin)
):
    """Whole User row as a dict — for debugging columns we don't yet
    surface in the typed endpoints."""
    async with async_session() as s:
        u = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="user not found")
    return {
        c.name: (
            _iso(getattr(u, c.name))
            if isinstance(getattr(u, c.name, None), datetime)
            else getattr(u, c.name, None)
        )
        for c in User.__table__.columns
    }


# ── Attention observability ─────────────────────────────────────────────────


def _short(value: str | None, n: int = 8) -> str | None:
    if not value:
        return None
    return str(value)[:n]


def _attention_summary(row: AttentionRow) -> dict[str, Any]:
    """Compact view of an attention row for the observe table."""
    payload = dict(row.payload or {})
    spec = payload.get("spec") or {}
    state = payload.get("current_state") or {}
    subject = spec.get("subject") if isinstance(spec, dict) else {}
    subject_name = (
        subject.get("name") if isinstance(subject, dict) else None
    )
    cadence = spec.get("cadence") if isinstance(spec, dict) else {}
    cad_type = (
        cadence.get("type") if isinstance(cadence, dict) else None
    )
    cad_params = (
        cadence.get("params") if isinstance(cadence, dict) else None
    )
    surface_policy = (
        spec.get("surface_policy") if isinstance(spec, dict) else {}
    )
    escalations = (
        surface_policy.get("escalations")
        if isinstance(surface_policy, dict)
        else None
    )
    nudge_policy = (
        surface_policy.get("nudge_policy")
        if isinstance(surface_policy, dict)
        else None
    )
    cursors = payload.get("poller_cursors") or {}
    return {
        "id": row.id,
        "id_short": _short(row.id),
        "user_id": row.user_id,
        "user_id_short": _short(row.user_id),
        "card": row.card,
        "status": row.status,
        "title": (spec.get("title") if isinstance(spec, dict) else None),
        "subject": subject_name,
        "cadence_type": cad_type,
        "cadence_params": cad_params,
        "value": state.get("value"),
        "value_numeric": state.get("value_numeric"),
        "target": state.get("target"),
        "progress": state.get("progress"),
        "count": state.get("count"),
        "last_event_at": state.get("last_event_at"),
        "day": state.get("day"),
        "rollup": state.get("rollup"),
        "evidence_ids": state.get("evidence_ids") or [],
        "escalations_n": (
            len(escalations) if isinstance(escalations, list) else 0
        ),
        "nudge_silent_for": (
            nudge_policy.get("if_silent_for_seconds")
            if isinstance(nudge_policy, dict)
            else None
        ),
        "poller_cursors": cursors,
        "last_update_at": payload.get("last_update_at"),
        "last_surfaced_at": _iso(row.last_surfaced_at),
        "created_at": _iso(row.created_at),
        "current_state": state,
    }


@router.get("/attention/observe")
async def attention_observe(
    _admin: str = Depends(_require_admin),
    user_id: str | None = Query(None, description="filter to one user"),
    ticks_limit: int = Query(50, ge=1, le=500),
    proactive_limit: int = Query(50, ge=1, le=500),
    schedule_limit: int = Query(50, ge=1, le=500),
    attentions_limit: int = Query(200, ge=1, le=1000),
):
    """Single endpoint feeding the /observe/attention page.

    Returns four parallel sections so the UI can render the whole picture
    in one shot:

      - ``attentions``: per-attention state snapshot (live + paused +
        recently surfaced). Sorted by ``last_update_at`` desc.
      - ``ticks``: append-only audit history across the user's attentions
        (or all users when ``user_id`` is None). Each tick carries the
        surface kind + rendered message + trigger.
      - ``proactive``: ChatMessage rows where ``is_proactive=True``,
        regardless of whether they were delivered (live) or persisted-
        only (shadow). This is *what Donna decided to say* across runners.
      - ``schedule``: pending DonnaSchedule rows ordered by ``fire_at``
        ascending — the "what's about to fire" queue.

    All four sections are scoped to ``user_id`` if provided, otherwise
    global. No write side-effects.
    """
    async with async_session() as session:
        # Worker pulse: max activity per worker family. Computed from
        # tick trigger prefixes + DonnaSchedule.fired_at, so we don't need
        # a heartbeat table.
        WORKER_LOOKBACK_TICKS = 500
        worker_stmt = (
            select(AttentionTickRow)
            .order_by(desc(AttentionTickRow.at))
            .limit(WORKER_LOOKBACK_TICKS)
        )
        worker_tick_rows = (
            await session.execute(worker_stmt)
        ).scalars().all()
        worker_pulse: dict[str, dict[str, Any]] = {}

        def _bump(name: str, when: datetime | None) -> None:
            if when is None:
                return
            entry = worker_pulse.setdefault(name, {"name": name, "n": 0, "last_at": None})
            entry["n"] += 1
            prior = entry["last_at"]
            if prior is None or when > prior:
                entry["last_at"] = when

        for t in worker_tick_rows:
            sc = t.source_counts or {}
            trigger = str(sc.get("trigger") or "").strip()
            if not trigger:
                continue
            prefix = trigger.split(":", 1)[0]
            mapping = {
                "observation": "log_observation_hook",
                "sweep": "attention_sweep_worker",
                "nudge_watcher": "attention_nudge_worker",
                "attention_schedule_materializer": "attention_schedule_materializer",
                "schedule_worker": "schedule_worker",
                "manual": "manual_invocation",
            }
            name = mapping.get(prefix, prefix)
            _bump(name, t.at)

        # schedule_worker fires (DonnaSchedule rows transitioning to fired=True)
        sched_fired = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.fired.is_(True))
                .order_by(desc(DonnaSchedule.fired_at))
                .limit(20)
            )
        ).scalars().all()
        for s in sched_fired:
            _bump("schedule_worker", s.fired_at)

        now_utc = datetime.now(timezone.utc)
        workers = []
        for entry in worker_pulse.values():
            last_at = entry["last_at"]
            since = (
                int((now_utc - last_at.replace(tzinfo=timezone.utc)).total_seconds())
                if last_at is not None
                else None
            )
            workers.append(
                {
                    "name": entry["name"],
                    "last_at": _iso(last_at),
                    "since_seconds": since,
                    "recent_count": entry["n"],
                }
            )
        workers.sort(key=lambda w: (w["since_seconds"] is None, w["since_seconds"] or 0))

        # Attentions
        att_stmt = select(AttentionRow).order_by(
            desc(AttentionRow.last_surfaced_at).nullslast(),
            desc(AttentionRow.created_at),
        ).limit(attentions_limit)
        if user_id:
            att_stmt = att_stmt.where(AttentionRow.user_id == user_id)
        att_rows = (await session.execute(att_stmt)).scalars().all()

        # Ticks
        tick_stmt = select(AttentionTickRow).order_by(
            desc(AttentionTickRow.at)
        ).limit(ticks_limit)
        if user_id:
            scoped_ids = [r.id for r in att_rows] or [""]
            tick_stmt = tick_stmt.where(
                AttentionTickRow.attention_id.in_(scoped_ids)
            )
        tick_rows = (await session.execute(tick_stmt)).scalars().all()

        # Proactive chat messages
        msg_stmt = (
            select(ChatMessage)
            .where(ChatMessage.is_proactive.is_(True))
            .order_by(desc(ChatMessage.created_at))
            .limit(proactive_limit)
        )
        if user_id:
            msg_stmt = msg_stmt.where(ChatMessage.user_id == user_id)
        msg_rows = (await session.execute(msg_stmt)).scalars().all()

        # Pending schedule
        sched_stmt = (
            select(DonnaSchedule)
            .where(DonnaSchedule.fired.is_(False))
            .where(DonnaSchedule.status == "pending")
            .order_by(DonnaSchedule.fire_at.asc())
            .limit(schedule_limit)
        )
        if user_id:
            sched_stmt = sched_stmt.where(DonnaSchedule.user_id == user_id)
        sched_rows = (await session.execute(sched_stmt)).scalars().all()

    attentions = [_attention_summary(r) for r in att_rows]
    by_card: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in attentions:
        by_card[a["card"] or "?"] = by_card.get(a["card"] or "?", 0) + 1
        by_status[a["status"] or "?"] = by_status.get(a["status"] or "?", 0) + 1

    return {
        "filter": {"user_id": user_id},
        "counts": {
            "attentions": len(attentions),
            "ticks": len(tick_rows),
            "proactive_messages": len(msg_rows),
            "pending_schedule": len(sched_rows),
            "by_card": by_card,
            "by_status": by_status,
        },
        "workers": workers,
        "attentions": attentions,
        "ticks": [
            {
                "id": t.id,
                "attention_id": t.attention_id,
                "attention_id_short": _short(t.attention_id),
                "at": _iso(t.at),
                "rendered_markdown": t.rendered_markdown,
                "warnings": t.warnings or [],
                "source_counts": t.source_counts or {},
            }
            for t in tick_rows
        ],
        "proactive": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "user_id_short": _short(m.user_id),
                "role": m.role,
                "content": m.content,
                "is_shadow": bool(m.is_shadow),
                "wa_message_id": m.wa_message_id,
                "created_at": _iso(m.created_at),
            }
            for m in msg_rows
        ],
        "schedule": [
            {
                "id": s.id,
                "id_short": _short(s.id),
                "user_id": s.user_id,
                "user_id_short": _short(s.user_id),
                "phone": s.phone,
                "fire_at": _iso(s.fire_at),
                "origin": s.origin,
                "recurrence": s.recurrence,
                "context": s.context or {},
                "attention_id": s.attention_id,
                "attention_id_short": _short(s.attention_id),
                "attempts": s.attempts,
                "last_error": s.last_error,
                "created_at": _iso(s.created_at),
            }
            for s in sched_rows
        ],
        "now": _iso(datetime.now(timezone.utc)),
    }


# ── Attention author + edit ──────────────────────────────────────────────────


_VALID_STATUS_TRANSITIONS = {"live", "paused", "resolved", "archived"}


@router.post("/attention/compose")
async def compose_attention(
    payload: dict = Body(...),
    _admin: str = Depends(_require_admin),
):
    """Author a new attention for a user from the staff dashboard.

    Body:
        {
          "user_id": "<uuid>",
          "raw_intent": "track my calories with a 2000 cal goal",
          "auto_live": true   # optional, default true
        }

    Reuses the same Sonnet 4.6 authoring pipeline that BRAIN's ``attend``
    tool uses, so the resulting AttentionSpec matches what a user would
    get if they typed the same thing on WhatsApp. Returns the persisted
    attention id + a dry-run preview (rendered markdown + source counts)
    so the staff caller can confirm the spec landed correctly.
    """
    user_id = str(payload.get("user_id") or "").strip()
    raw_intent = str(payload.get("raw_intent") or "").strip()
    auto_live = bool(payload.get("auto_live", True))
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not raw_intent:
        raise HTTPException(status_code=400, detail="raw_intent required")

    try:
        from donna.attention.tools import create_attention as _create
    except Exception as e:
        logger.exception("admin: attention create import failed")
        raise HTTPException(status_code=503, detail=f"compose pipeline unavailable: {e}")

    try:
        result = await _create(raw_intent, user_id, auto_live=auto_live)
    except Exception as e:
        logger.exception("admin: attention compose failed")
        raise HTTPException(status_code=500, detail=str(e)[:500])

    spec = result.attention.spec
    preview = result.preview
    return {
        "attention_id": str(result.attention.id),
        "user_id": str(result.attention.user_id),
        "reused": result.reused,
        "authored_via": result.authored_via,
        "authored_confidence": result.authored_confidence,
        "spec": spec.model_dump(mode="json"),
        "preview": {
            "rendered_markdown": getattr(preview, "rendered_markdown", None),
            "warnings": list(getattr(preview, "warnings", []) or []),
            "source_previews": [
                {
                    "source_type": p.source_type.value
                    if hasattr(p.source_type, "value")
                    else str(p.source_type),
                    "item_count": p.item_count,
                }
                for p in (getattr(preview, "source_previews", []) or [])
            ],
        },
    }


# ── Proactive trace: forensics for ANY proactive message ───────────────────


def _ts_within(a: datetime | None, b: datetime, *, seconds: int) -> bool:
    if a is None:
        return False
    aa = a if a.tzinfo else a.replace(tzinfo=timezone.utc)
    bb = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
    return abs((aa - bb).total_seconds()) <= seconds


def _read_events_around(
    *,
    user_id: str,
    center: datetime,
    window_seconds: int = 300,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Pull events for ``user_id`` whose ts is within ±window of center.

    Walks the JSONL forward (it's append-only, oldest first); we stop
    once we go past the upper bound. Cheap when the file is small; for
    larger files we should index by date later.
    """
    if not _EVENTS_LOG_PATH.exists():
        return []
    lower = center - timedelta(seconds=window_seconds)
    upper = center + timedelta(seconds=window_seconds)
    out: list[dict[str, Any]] = []
    try:
        with _EVENTS_LOG_PATH.open("r", encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                ts_raw = ev.get("ts")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(
                        str(ts_raw).replace("Z", "+00:00")
                    )
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if ts < lower:
                    continue
                if ts > upper:
                    break
                if ev.get("user_id") and ev.get("user_id") != user_id:
                    continue
                out.append(ev)
                if len(out) > limit * 4:
                    break
    except Exception:
        logger.exception("admin: events.jsonl window read failed")
    # Keep most recent ``limit`` since we may have logged anonymous
    # (user_id-less) events from worker subprocesses around the turn.
    return out[-limit:]


@router.get("/proactive/trace")
async def proactive_trace(
    message_id: str = Query(..., description="ChatMessage id"),
    window_seconds: int = Query(300, ge=10, le=3600),
    _admin: str = Depends(_require_admin),
):
    """Causal-chain trace for ONE proactive message.

    Joins everything we have about *why* a proactive message went out:

      1. ChatMessage row itself
      2. ProactivePing within ±window (only dispatcher writes these)
      3. proactive_signals fired in ±window for the same user (websets)
         — best-effort title/content match against the message body
      4. proactive_subscriptions referenced by intent_key
      5. DonnaSchedule rows fired in ±window (schedule_worker path)
      6. AttentionRow surfaces matching the topic_key, last_surfaced_at
         in window, or referenced by a fired DonnaSchedule
      7. events.jsonl entries in ±window: turn.start, prompt.snapshot,
         tool.call, turn.end (cost), errors

    Returns ``probable_source`` ("dispatcher" | "webset" | "schedule" |
    "attention" | "unknown") based on which signal lines up best in time.
    """
    async with async_session() as session:
        msg = (
            await session.execute(
                select(ChatMessage).where(ChatMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if msg is None:
            raise HTTPException(status_code=404, detail="message not found")
        if not msg.is_proactive:
            raise HTTPException(
                status_code=400,
                detail="message is not proactive — trace surface is for proactive only",
            )
        user_id = msg.user_id
        center_naive = msg.created_at
        center = center_naive.replace(tzinfo=timezone.utc) if center_naive.tzinfo is None else center_naive
        lower = center_naive - timedelta(seconds=window_seconds)
        upper = center_naive + timedelta(seconds=window_seconds)

        # Sibling proactive messages in the same window (helps see bursts)
        siblings = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .where(ChatMessage.is_proactive.is_(True))
                .where(ChatMessage.created_at >= lower)
                .where(ChatMessage.created_at <= upper)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()

        # ProactivePing rows in window
        pings = (
            await session.execute(
                select(ProactivePing)
                .where(ProactivePing.user_id == user_id)
                .where(ProactivePing.fired_at >= lower)
                .where(ProactivePing.fired_at <= upper)
                .order_by(ProactivePing.fired_at)
            )
        ).scalars().all()

        # DonnaSchedule rows fired in window
        sched_fired = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.user_id == user_id)
                .where(DonnaSchedule.fired.is_(True))
                .where(DonnaSchedule.fired_at.is_not(None))
                .where(DonnaSchedule.fired_at >= lower)
                .where(DonnaSchedule.fired_at <= upper)
                .order_by(DonnaSchedule.fired_at)
            )
        ).scalars().all()

        # proactive_signals + their owning subscriptions
        from sqlalchemy import text as _text

        sig_rows = (
            await session.execute(
                _text(
                    "SELECT id, intent_key, payload, arrived_at, consumed_at, subscription_id "
                    "FROM proactive_signals "
                    "WHERE user_id = :u AND arrived_at BETWEEN :lo AND :hi "
                    "ORDER BY arrived_at"
                ),
                {"u": user_id, "lo": lower, "hi": upper},
            )
        ).fetchall()
        signals: list[dict[str, Any]] = []
        intent_keys: set[str] = set()
        for r in sig_rows:
            payload = r[2] if isinstance(r[2], dict) else {}
            title = (payload.get("title") or payload.get("summary") or "")
            url = payload.get("url") or ""
            highlights = payload.get("highlights") or []
            if isinstance(highlights, list):
                highlights = highlights[:3]
            signals.append({
                "id": r[0],
                "intent_key": r[1],
                "subscription_id": r[5],
                "arrived_at": _iso(r[3]),
                "consumed_at": _iso(r[4]),
                "title": str(title)[:240],
                "url": str(url)[:300],
                "highlights": [str(h)[:240] for h in highlights] if isinstance(highlights, list) else [],
            })
            if r[1]:
                intent_keys.add(str(r[1]))

        subs: list[dict[str, Any]] = []
        if intent_keys:
            sub_rows = (
                await session.execute(
                    _text(
                        "SELECT id, intent_key, description, webset_id, monitor_id, cadence, "
                        "       active, created_at, last_refreshed_at, last_hit_at "
                        "FROM proactive_subscriptions "
                        "WHERE user_id = :u AND intent_key = ANY(:keys)"
                    ),
                    {"u": user_id, "keys": list(intent_keys)},
                )
            ).fetchall()
            for r in sub_rows:
                subs.append({
                    "id": r[0],
                    "intent_key": r[1],
                    "description": r[2],
                    "webset_id": r[3],
                    "monitor_id": r[4],
                    "cadence": r[5],
                    "active": bool(r[6]),
                    "created_at": _iso(r[7]),
                    "last_refreshed_at": _iso(r[8]),
                    "last_hit_at": _iso(r[9]),
                })

        # Attentions whose last_surfaced_at falls in this window OR whose
        # id matches a sibling DonnaSchedule.attention_id.
        att_ids: set[str] = set()
        for s in sched_fired:
            if s.attention_id:
                att_ids.add(s.attention_id)
        att_stmt = (
            select(AttentionRow)
            .where(AttentionRow.user_id == user_id)
            .where(AttentionRow.last_surfaced_at >= lower)
            .where(AttentionRow.last_surfaced_at <= upper)
        )
        attns = (await session.execute(att_stmt)).scalars().all()
        for a in attns:
            att_ids.add(a.id)
        if att_ids:
            attn_rows = (
                await session.execute(
                    select(AttentionRow).where(AttentionRow.id.in_(list(att_ids)))
                )
            ).scalars().all()
        else:
            attn_rows = []

    # events.jsonl in the same window — turn lifecycle + tool calls + cost
    events = _read_events_around(
        user_id=user_id, center=center, window_seconds=window_seconds, limit=200
    )
    turns: dict[str, dict[str, Any]] = {}
    for e in events:
        tid = e.get("turn_id") or ""
        if not tid:
            continue
        bucket = turns.setdefault(
            tid,
            {
                "turn_id": tid,
                "started_at": None,
                "ended_at": None,
                "mode": None,
                "tools": [],
                "in_tokens": None,
                "out_tokens": None,
                "cache_read": None,
                "cache_creation": None,
                "cost_usd": None,
                "model": None,
                "errors": [],
                "prompt_snapshot": None,
            },
        )
        ev = e.get("event", "")
        ts = e.get("ts")
        if ev == "turn.start":
            bucket["started_at"] = ts
            bucket["mode"] = e.get("mode")
        elif ev == "turn.end":
            bucket["ended_at"] = ts
            for k in ("in_tokens", "out_tokens", "cache_read", "cache_creation", "cost_usd", "model"):
                if e.get(k) is not None:
                    bucket[k] = e.get(k)
        elif ev == "tool.call":
            bucket["tools"].append({
                "ts": ts,
                "tool": e.get("tool"),
                "short": e.get("short"),
                "input_keys": e.get("input_keys") or [],
            })
        elif ev == "prompt.snapshot":
            bucket["prompt_snapshot"] = {
                "system_len": e.get("system_prompt_len"),
                "user_len": e.get("wrapped_user_prompt_len"),
                "model": e.get("model"),
                "tool_mode": e.get("tool_mode"),
            }
        elif ev == "error":
            bucket["errors"].append({"ts": ts, "msg": str(e.get("msg") or e.get("detail") or "")[:300]})

    # Best-effort source classification
    probable_source = "unknown"
    confidence = 0.0
    rationale: list[str] = []
    msg_text_low = (msg.content or "").lower()

    # 1. dispatcher Tier 2 → ProactivePing
    matching_pings = [p for p in pings if _ts_within(p.fired_at, center, seconds=120)]
    if matching_pings:
        probable_source = "dispatcher_tier2"
        confidence = 0.9
        rationale.append(f"ProactivePing in window: {[p.source for p in matching_pings]}")

    # 2. webset → proactive_signals + subscription, by title overlap
    matched_signals = []
    for s in signals:
        title = (s.get("title") or "").lower()
        if not title:
            continue
        # rough token overlap: any 4+ char word from title appears in message
        words = [w for w in title.split() if len(w) >= 4]
        if any(w in msg_text_low for w in words):
            matched_signals.append(s)
    if matched_signals:
        if confidence < 0.8:
            probable_source = "webset_subscription"
            confidence = 0.85
        rationale.append(
            f"webset signal title overlap: {len(matched_signals)} match(es)"
        )

    # 3. schedule worker fire
    if sched_fired and probable_source == "unknown":
        probable_source = "schedule_worker"
        confidence = 0.7
        rationale.append(f"DonnaSchedule fired in window: {len(sched_fired)}")

    # 4. attention surface
    if attn_rows and probable_source == "unknown":
        probable_source = "attention_runtime"
        confidence = 0.6
        rationale.append(
            f"AttentionRow.last_surfaced_at in window: {len(attn_rows)}"
        )

    return {
        "message": {
            "id": msg.id,
            "user_id": msg.user_id,
            "role": msg.role,
            "content": msg.content,
            "is_proactive": bool(msg.is_proactive),
            "is_shadow": bool(msg.is_shadow),
            "wa_message_id": msg.wa_message_id,
            "created_at": _iso(msg.created_at),
        },
        "window_seconds": window_seconds,
        "probable_source": probable_source,
        "confidence": confidence,
        "rationale": rationale,
        "siblings": [
            {
                "id": s.id,
                "content": (s.content or "")[:240],
                "is_shadow": bool(s.is_shadow),
                "created_at": _iso(s.created_at),
                "self": s.id == msg.id,
            }
            for s in siblings
        ],
        "proactive_pings": [
            {
                "id": p.id,
                "source": p.source,
                "topic_key": p.topic_key,
                "message_ref": p.message_ref,
                "suppressed_reason": p.suppressed_reason,
                "fired_at": _iso(p.fired_at),
            }
            for p in pings
        ],
        "schedule_fired": [
            {
                "id": s.id,
                "fire_at": _iso(s.fire_at),
                "fired_at": _iso(s.fired_at),
                "origin": s.origin,
                "attention_id": s.attention_id,
                "context": s.context or {},
                "last_error": s.last_error,
            }
            for s in sched_fired
        ],
        "signals": signals,
        "subscriptions": subs,
        "attentions": [
            {
                "id": a.id,
                "card": a.card,
                "status": a.status,
                "title": (a.payload or {}).get("spec", {}).get("title")
                if isinstance((a.payload or {}).get("spec"), dict)
                else None,
                "last_surfaced_at": _iso(a.last_surfaced_at),
                "current_state": (a.payload or {}).get("current_state") or {},
            }
            for a in attn_rows
        ],
        "turns": list(turns.values()),
        "now": _iso(datetime.now(timezone.utc)),
    }


@router.post("/attention/{attention_id}/status")
async def update_attention_status(
    attention_id: str,
    payload: dict = Body(...),
    _admin: str = Depends(_require_admin),
):
    """Transition an attention's lifecycle status.

    Body: ``{"status": "live" | "paused" | "resolved" | "cancelled"}``.

    Maps to the existing single-purpose helpers so the side effects
    (cancel materialized fires, etc.) stay in one place.
    """
    new_status = str(payload.get("status") or "").strip().lower()
    if new_status not in _VALID_STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_VALID_STATUS_TRANSITIONS)}",
        )

    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore
    except Exception as e:
        logger.exception("admin: status import failed")
        raise HTTPException(status_code=503, detail=f"store unavailable: {e}")

    status_map = {
        "live": AttentionStatus.LIVE,
        "paused": AttentionStatus.PAUSED,
        "resolved": AttentionStatus.RESOLVED,
        "archived": AttentionStatus.QUIETLY_ARCHIVED,
    }
    target = status_map.get(new_status)
    if target is None:
        raise HTTPException(status_code=400, detail=f"unsupported status {new_status}")

    try:
        store = AttentionStore()
        updated = store.update_status(attention_id, target)
    except Exception as e:
        logger.exception("admin: status update failed id=%s", attention_id[:8])
        raise HTTPException(status_code=500, detail=str(e)[:500])

    if updated is None:
        raise HTTPException(status_code=404, detail="attention not found")

    return {
        "attention_id": str(updated.id),
        "status": target.value,
        "now": _iso(datetime.now(timezone.utc)),
    }
