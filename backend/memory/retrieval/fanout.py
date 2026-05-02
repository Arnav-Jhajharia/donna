"""Parallel fanout to semantic and structured memory lanes."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.memory.clients.graphiti import search_facts as graphiti_search
from backend.memory.clients.supermemory import get_memory_client
from backend.memory.retrieval.structured_hints import (
    StructuredHints,
    detect_structured_hints,
    query_terms,
)
from backend.memory.retrieval.types import RetrievalResult
from backend.memory.time import format_local, period_bounds, timezone_label, utcnow_naive

logger = logging.getLogger(__name__)

_PER_QUERY_LIMIT = 6
_LANE_TIMEOUT = 8.0

# A chunk that looks like a USER:/DONNA: chat fragment AND was ingested
# inside this window gets its score halved at the documents lane. Rationale:
# the wrapped prompt already includes RECENT CHAT, so surfacing the same
# fragments through recall both crowds out long-term memories AND duplicates
# context the model already sees. PDFs/notes/emails don't match the chat
# regex so they keep their full weight.
_CHAT_FRAGMENT_RECENT_DAYS = 30
_CHAT_FRAGMENT_DOWNWEIGHT = 0.5
_CHAT_FRAGMENT_RE = re.compile(r"(?im)^\s*(user|donna)\s*:")


async def fanout(
    *,
    user_id: str,
    queries: list[str],
    original_message: str = "",
    per_query_limit: int = _PER_QUERY_LIMIT,
    use_supermemory: bool = True,
    use_graphiti: bool = True,
    use_observations: bool = True,
    use_open_loops: bool = True,
    use_situation_brief: bool = True,
    use_documents: bool = True,
    use_calendar: bool = True,
) -> list[RetrievalResult]:
    tasks: list[asyncio.Task] = []
    hints = detect_structured_hints(original_message, queries)
    structured_query = original_message or " ".join(queries)

    if use_observations:
        tasks.append(
            asyncio.create_task(
                _search_observations(user_id, structured_query, hints, per_query_limit)
            )
        )
    if use_open_loops:
        tasks.append(
            asyncio.create_task(
                _search_open_loops(user_id, structured_query, hints, per_query_limit)
            )
        )
    if use_situation_brief and hints.wants_situation_brief:
        tasks.append(
            asyncio.create_task(
                _search_situation_brief(user_id, structured_query)
            )
        )
    if use_calendar:
        tasks.append(
            asyncio.create_task(
                _search_calendar(user_id, structured_query, hints, per_query_limit)
            )
        )

    for q in queries:
        if not q.strip():
            continue
        if use_supermemory:
            tasks.append(asyncio.create_task(_search_sm(user_id, q, per_query_limit)))
        if use_graphiti:
            tasks.append(asyncio.create_task(_search_gt(user_id, q, per_query_limit)))
        if use_documents:
            tasks.append(asyncio.create_task(_search_docs(user_id, q, per_query_limit)))
    if not tasks:
        return []
    batched = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[RetrievalResult] = []
    for b in batched:
        if isinstance(b, Exception):
            logger.warning("fanout lane failed: %s", b)
            continue
        results.extend(b)
    return results


async def _search_observations(
    user_id: str,
    query: str,
    hints: StructuredHints,
    limit: int,
) -> list[RetrievalResult]:
    try:
        from sqlalchemy import cast, or_, select
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy import Text

        from backend.db.models import Observation, User
        from backend.db.session import async_session
    except Exception:
        logger.exception("fanout.observations imports failed")
        return []

    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            bounds = period_bounds(hints.period, timezone_name)
            if bounds:
                since, until = bounds
            else:
                since = utcnow_naive() - timedelta(days=14)
                until = None

            stmt = (
                select(Observation)
                .where(Observation.user_id == user_id)
                .where(Observation.event_time >= since)
                .order_by(Observation.event_time.desc())
                .limit(max(limit, 8))
            )
            if until is not None:
                stmt = stmt.where(Observation.event_time < until)
            if hints.observation_type:
                stmt = stmt.where(Observation.type == hints.observation_type)
            elif not hints.wants_observations:
                terms = query_terms(query)
                if not terms:
                    return []
                clauses = []
                fields_text = cast(cast(Observation.fields, JSONB), Text)
                tags_text = cast(cast(Observation.tags, JSONB), Text)
                for term in terms[:5]:
                    pat = f"%{term}%"
                    clauses.extend(
                        [
                            Observation.raw.ilike(pat),
                            Observation.type.ilike(pat),
                            fields_text.ilike(pat),
                            tags_text.ilike(pat),
                        ]
                    )
                stmt = stmt.where(or_(*clauses))

            rows = (await asyncio.wait_for(session.execute(stmt), timeout=_LANE_TIMEOUT)).scalars().all()
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.observations failed")
        return []

    if not rows:
        return []

    period_label = hints.period or "recent"
    type_label = hints.observation_type or "observation"
    aggregate = _aggregate_observations(rows)
    summary = _render_observation_summary(
        rows,
        timezone_name=timezone_name,
        type_label=type_label,
        period_label=period_label,
        aggregate=aggregate,
    )
    results = [
        RetrievalResult(
            id=f"obs:summary:{_hash(user_id + query + type_label + period_label)}",
            source="observations",
            content=summary,
            score=2.0 if hints.wants_observations else 0.65,
            retrieved_via=query,
            metadata={
                "period": hints.period,
                "observation_type": hints.observation_type,
                "aggregate": aggregate,
                "row_count": len(rows),
                "structured_priority": 0.08 if hints.wants_observations else 0.0,
            },
        )
    ]
    for idx, row in enumerate(rows[:limit]):
        content = _render_observation_row(row, timezone_name)
        results.append(
            RetrievalResult(
                id=f"obs:{row.id}",
                source="observations",
                content=content,
                score=max(0.2, 0.9 - idx * 0.05),
                retrieved_via=query,
                metadata={
                    "type": row.type,
                    "event_time": row.event_time.isoformat() if row.event_time else None,
                    "event_time_local": format_local(row.event_time, timezone_name),
                    "fields": row.fields,
                    "tags": row.tags,
                    "raw": row.raw,
                },
            )
        )
    return results


async def _search_open_loops(
    user_id: str,
    query: str,
    hints: StructuredHints,
    limit: int,
) -> list[RetrievalResult]:
    try:
        from backend.db.session import async_session
        from backend.memory.tools._open_loop_view import read_open_loops_unified
    except Exception:
        logger.exception("fanout.open_loops imports failed")
        return []

    terms = query_terms(query)
    if not hints.wants_open_loops and not terms:
        return []
    content_terms = None if hints.wants_open_loops else terms[:6]
    try:
        async with async_session() as session:
            rows = await asyncio.wait_for(
                read_open_loops_unified(
                    session,
                    user_id=user_id,
                    statuses=("active",),
                    limit=max(limit, 10),
                    content_terms=content_terms,
                ),
                timeout=_LANE_TIMEOUT,
            )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.open_loops failed")
        return []

    # When the user explicitly asks "open loops" / "what am i tracking" the
    # rows must survive rerank against the multi-group RRF noise from docs +
    # supermemory. structured_priority is added directly into rrf score by
    # the reranker (see backend/memory/retrieval/rerank.py).
    structured_priority = 0.20 if hints.wants_open_loops else 0.0
    return [
        RetrievalResult(
            id=f"loop:{row.id}",
            source="open_loops",
            content=f"open loop active since {row.created_at.isoformat() if row.created_at else 'unknown'}: {row.content}",
            score=max(0.2, 1.0 - idx * 0.05) if hints.wants_open_loops else max(0.2, 0.7 - idx * 0.05),
            retrieved_via=query,
            metadata={
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "source_message": row.source_message,
                "structured_priority": structured_priority,
            },
        )
        for idx, row in enumerate(rows[:limit])
    ]


async def _search_situation_brief(user_id: str, query: str) -> list[RetrievalResult]:
    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        logger.exception("fanout.situation_brief imports failed")
        return []

    try:
        async with async_session() as session:
            user = (
                await asyncio.wait_for(
                    session.execute(select(User).where(User.id == user_id)),
                    timeout=_LANE_TIMEOUT,
                )
            ).scalar_one_or_none()
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.situation_brief failed")
        return []
    if user is None or not user.living_profile:
        return []
    brief = dict(user.living_profile or {}).get("situation_brief")
    if not isinstance(brief, dict):
        return []
    content = _render_situation_brief(brief)
    if not content:
        return []
    return [
        RetrievalResult(
            id=f"brief:{_hash(user_id + content)}",
            source="situation_brief",
            content=content,
            score=1.05,
            retrieved_via=query,
            metadata={
                "generated_at": brief.get("generated_at"),
                "evidence_used": brief.get("evidence_used"),
            },
        )
    ]


async def _search_calendar(
    user_id: str,
    query: str,
    hints: StructuredHints,
    limit: int,
) -> list[RetrievalResult]:
    """Calendar lane: searches CalendarEntry rows around the query period.

    Closes the recall fanout coverage gap noted in CLAUDE.md
    ("Calendar [...] NOT yet in the fanout"). Defaults to a +/-7d window
    when the query has no explicit period; uses period bounds when present.
    Term-matches against title and location.
    """
    try:
        from sqlalchemy import or_, select

        from backend.db.models import CalendarEntry, User
        from backend.db.session import async_session
    except Exception:
        logger.exception("fanout.calendar imports failed")
        return []

    terms = query_terms(query)
    if not hints.wants_calendar and not terms:
        return []

    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            bounds = period_bounds(hints.period, timezone_name)
            if bounds:
                since, until = bounds
            else:
                now = utcnow_naive()
                since = now - timedelta(days=7)
                until = now + timedelta(days=7)

            stmt = (
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.start_time >= since)
                .where(CalendarEntry.start_time < until)
                .order_by(CalendarEntry.start_time.asc())
                .limit(max(limit, 8))
            )
            # If the user didn't explicitly invoke calendar phrasing, gate on
            # term overlap with title/location so we don't dump random events
            # into every recall.
            if not hints.wants_calendar and terms:
                clauses = []
                for term in terms[:5]:
                    pat = f"%{term}%"
                    clauses.append(CalendarEntry.title.ilike(pat))
                    clauses.append(CalendarEntry.location.ilike(pat))
                stmt = stmt.where(or_(*clauses))

            rows = (
                await asyncio.wait_for(session.execute(stmt), timeout=_LANE_TIMEOUT)
            ).scalars().all()
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.calendar failed")
        return []

    if not rows:
        return []

    results: list[RetrievalResult] = []
    for idx, row in enumerate(rows[:limit]):
        when = format_local(row.start_time, timezone_name) or "unknown time"
        location = f" @ {row.location}" if row.location else ""
        content = f"calendar: {row.title} at {when}{location}"
        # wants_calendar queries get a structured priority bump so calendar
        # results compete with supermemory/graphiti at rerank time.
        base = 1.4 if hints.wants_calendar else 0.7
        results.append(
            RetrievalResult(
                id=f"cal:{row.id}",
                source="calendar",
                content=content,
                score=max(0.2, base - idx * 0.05),
                retrieved_via=query,
                metadata={
                    "start_time": row.start_time.isoformat() if row.start_time else None,
                    "end_time": row.end_time.isoformat() if row.end_time else None,
                    "location": row.location,
                    "title": row.title,
                    "category": row.category,
                    "structured_priority": 0.05 if hints.wants_calendar else 0.0,
                },
            )
        )
    return results


async def _search_sm(user_id: str, query: str, limit: int) -> list[RetrievalResult]:
    try:
        hits = await asyncio.wait_for(
            get_memory_client().search_with_graph(user_id, query, limit=limit),
            timeout=_LANE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.sm failed")
        return []
    return [
        RetrievalResult(
            id=f"sm:{h.id}",
            source="supermemory",
            content=h.content,
            score=h.score,
            retrieved_via=query,
            metadata={"updated_at": h.updated_at, "relations": h.relations, **h.metadata},
        )
        for h in hits
        if h.id
    ]


async def _search_docs(user_id: str, query: str, limit: int) -> list[RetrievalResult]:
    """Documents lane — chunks of any user-uploaded PDF / image-extracted-text /
    long-content ingest. Hits the Supermemory Documents endpoint (separate from
    the Memories endpoint that ``_search_sm`` queries).

    Without this lane, recall(auto) misses everything inside chunked documents
    and the brain has to know to call ``recall_document_chunks`` separately —
    which it usually doesn't.
    """
    try:
        chunks = await asyncio.wait_for(
            get_memory_client().search_document_chunks(user_id, query, limit=limit),
            timeout=_LANE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.docs failed")
        return []
    results: list[RetrievalResult] = []
    for c in chunks:
        if not c.content:
            continue
        # Stable id: doc + content hash so duplicate hits across query
        # facets dedupe at rerank time.
        chunk_id = f"doc:{c.doc_id or 'unknown'}:{_hash(c.content)}"
        meta = dict(c.metadata or {})
        meta.setdefault("doc_id", c.doc_id)
        score = float(c.score or 0.0)
        # Behavioral change: chunks that look like USER:/DONNA: chat fragments
        # AND were ingested in the last 30d are halved. The wrapped prompt
        # already shows RECENT CHAT to the model, so surfacing those same
        # fragments through recall is doubly redundant AND outranks real
        # long-term hits (PDFs, notes, supermemory narrative). Real document
        # bodies don't match _CHAT_FRAGMENT_RE so they keep full weight.
        if _is_recent_chat_fragment(c.content, meta):
            score *= _CHAT_FRAGMENT_DOWNWEIGHT
            meta["chat_fragment_downweight"] = _CHAT_FRAGMENT_DOWNWEIGHT
        results.append(
            RetrievalResult(
                id=chunk_id,
                source="documents",
                content=c.content,
                score=score,
                retrieved_via=query,
                metadata=meta,
            )
        )
    return results


def _is_recent_chat_fragment(content: str, meta: dict[str, Any]) -> bool:
    """True iff content looks like a chat transcript AND is fresh.

    "Looks like chat" = at least one ``USER:`` or ``DONNA:`` line prefix.
    "Fresh" = ingested/created within ``_CHAT_FRAGMENT_RECENT_DAYS``. If we
    can't determine freshness from metadata, default to True (treat as fresh)
    so the downweight applies — the goal is to suppress chat-style fragments,
    not preserve old ones.
    """
    if not content or not _CHAT_FRAGMENT_RE.search(content):
        return False
    candidates = (
        meta.get("created_at"),
        meta.get("updated_at"),
        meta.get("ingested_at"),
        meta.get("date"),
    )
    raw_meta = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else None
    if raw_meta:
        candidates = candidates + (
            raw_meta.get("created_at"),
            raw_meta.get("updated_at"),
            raw_meta.get("ingested_at"),
            raw_meta.get("date"),
        )
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CHAT_FRAGMENT_RECENT_DAYS)
    for value in candidates:
        ts = _parse_iso_dt(value)
        if ts is None:
            continue
        return ts >= cutoff
    # No timestamp available — assume the chunk is fresh enough to downweight.
    return True


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _search_gt(user_id: str, query: str, limit: int) -> list[RetrievalResult]:
    try:
        facts = await asyncio.wait_for(
            graphiti_search(user_id, query, limit=limit), timeout=_LANE_TIMEOUT
        )
    except asyncio.TimeoutError:
        return []
    except Exception:
        logger.exception("fanout.gt failed")
        return []
    return [
        RetrievalResult(
            id=f"gt:{f.get('uuid') or _hash(f.get('fact', ''))}",
            source="graphiti",
            content=f.get("fact", ""),
            score=1.0,
            retrieved_via=query,
            metadata={
                "valid_at": f.get("valid_at"),
                "invalid_at": f.get("invalid_at"),
                "created_at": f.get("created_at"),
                "episodes": f.get("episodes") or [],
            },
        )
        for f in facts
        if f.get("fact")
    ]


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def _render_observation_row(row: Any, timezone_name: str | None) -> str:
    when = format_local(row.event_time, timezone_name) or "unknown time"
    fields = _compact_dict(row.fields or {})
    raw = f" raw={row.raw}" if row.raw else ""
    return f"{row.type} observation at {when}: {fields}{raw}"


def _render_observation_summary(
    rows: list[Any],
    *,
    timezone_name: str | None,
    type_label: str,
    period_label: str,
    aggregate: dict[str, Any],
) -> str:
    tz = timezone_label(timezone_name)
    prefix = f"{type_label} observations {period_label}: {len(rows)} row{'s' if len(rows) != 1 else ''}"
    totals = aggregate.get("totals_by_currency") or {}
    if totals:
        rendered = ", ".join(f"{amount:g} {currency}" for currency, amount in sorted(totals.items()))
        prefix += f", total {rendered}"
    elif aggregate.get("numeric"):
        rendered = ", ".join(
            f"{key} sum {vals['sum']:g}, avg {vals['avg']:g}"
            for key, vals in sorted(aggregate["numeric"].items())
        )
        prefix += f", {rendered}"
    examples = "; ".join(_render_observation_row(r, timezone_name) for r in rows[:4])
    return f"{prefix}. timezone {tz}. {examples}"


def _aggregate_observations(rows: list[Any]) -> dict[str, Any]:
    totals_by_currency: dict[str, float] = {}
    numeric: dict[str, list[float]] = {}
    for row in rows:
        fields = row.fields or {}
        if row.type == "expense":
            amount, currency = _expense_amount(fields)
            if amount is not None:
                totals_by_currency[currency] = totals_by_currency.get(currency, 0.0) + amount
        for key, value in fields.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric.setdefault(str(key), []).append(float(value))
    numeric_summary = {
        key: {"sum": sum(values), "avg": sum(values) / len(values), "count": len(values)}
        for key, values in numeric.items()
        if values
    }
    return {
        "totals_by_currency": totals_by_currency,
        "numeric": numeric_summary,
    }


def _expense_amount(fields: dict[str, Any]) -> tuple[float | None, str]:
    currency = str(fields.get("currency") or "").upper()
    for key, value in fields.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        key_s = str(key).lower()
        if key_s == "amount":
            return float(value), currency or "UNKNOWN"
        if key_s.startswith("amount_"):
            return float(value), key_s.removeprefix("amount_").upper()
    return None, currency or "UNKNOWN"


def _compact_dict(value: dict[str, Any]) -> str:
    parts = []
    for key, item in sorted(value.items()):
        parts.append(f"{key}={item}")
    return ", ".join(parts) if parts else "{}"


def _render_situation_brief(brief: dict[str, Any]) -> str:
    lines: list[str] = []
    if brief.get("generated_at"):
        lines.append(f"situation brief generated_at: {brief['generated_at']}")
    for key in ("current_status", "open_loops", "this_week", "next_week", "last_week"):
        value = brief.get(key)
        if isinstance(value, list) and value:
            lines.append(f"{key}: " + "; ".join(str(v) for v in value[:5]))
        elif isinstance(value, str) and value.strip():
            lines.append(f"{key}: {value.strip()}")
    evidence = brief.get("evidence_used")
    if isinstance(evidence, dict) and evidence:
        lines.append("evidence_used: " + _compact_dict(evidence))
    return "\n".join(lines)
