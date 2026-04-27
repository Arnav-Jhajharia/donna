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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import desc, func, select

from backend.db.session import async_session
from db.models import (
    CalendarEntry,
    ChatMessage,
    EmailMessage,
    Integration,
    Observation,
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
