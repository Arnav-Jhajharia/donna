"""Adapter: read open_loops via attentions(card='open_loop') with legacy fallback.

Phase 1c of the open_loops → attentions consolidation. Phase 1a wired
dual-write; Phase 1b backfilled history. This module flips readers to
the unified path.

Strategy: every read queries ``attentions WHERE card='open_loop'`` first,
then UNIONs in any legacy ``open_loops`` rows that don't have a mirror
yet (guards against the rare best-effort mirror failure during Phase 1a).
The fallback drops out cleanly in Phase 1d when the legacy table is
removed.

The returned ``OpenLoopView`` dataclass mimics the legacy ``OpenLoop``
ORM model surface (``id``, ``user_id``, ``content``, ``status``,
``created_at``, ``due_at``, ``resolved_at``, ``source_message``) so
existing readers can swap their source with a one-line import change.

Status mapping (attentions ↔ open_loops):
    attentions.status='live'      <→  open_loops.status='active'
    attentions.status='resolved'  <→  open_loops.status='closed'

The view's ``status`` field is normalized back to the legacy vocabulary
so existing filters like ``status == 'active'`` keep working unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_OPEN_LOOP_CARD = "open_loop"

# attentions.status → open_loops.status (legacy vocabulary)
_STATUS_TO_LEGACY = {
    "live": "active",
    "resolved": "closed",
    "expired": "closed",
    "rejected": "closed",
    "quietly_archived": "closed",
}

# legacy open_loops.status → attentions.status (for filtering)
_LEGACY_TO_ATTENTION_STATUS = {
    "active": ["live"],
    "closed": ["resolved", "expired", "rejected", "quietly_archived"],
    "resolved": ["resolved"],
}


@dataclass(frozen=True)
class OpenLoopView:
    """Read-only view that mimics the legacy ``OpenLoop`` ORM row.

    Sourced from either ``attentions`` (preferred) or the legacy
    ``open_loops`` table (fallback for unmirrored rows).
    """
    id: str
    user_id: str
    content: str
    status: str  # legacy vocab: 'active' | 'closed'
    created_at: datetime | None
    due_at: datetime | None
    source_message: str | None
    resolved_at: datetime | None
    source: str = "attentions"  # "attentions" or "open_loops_legacy"


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _attention_to_view(row: Any) -> OpenLoopView:
    """Map AttentionRow + payload → OpenLoopView."""
    payload = row.payload or {}
    spec = payload.get("spec") if isinstance(payload, dict) else {}
    spec = spec or {}
    legacy_id = payload.get("mirror_open_loop_id") or row.id
    content = spec.get("rationale") or row.title or ""
    legacy_status = _STATUS_TO_LEGACY.get(row.status, "active")
    return OpenLoopView(
        id=str(legacy_id),
        user_id=row.user_id,
        content=content,
        status=legacy_status,
        created_at=row.created_at,
        due_at=_parse_iso(spec.get("due_at")),
        source_message=payload.get("source_message"),
        resolved_at=row.updated_at if legacy_status == "closed" else None,
        source="attentions",
    )


def _legacy_to_view(row: Any) -> OpenLoopView:
    """Map legacy OpenLoop ORM row → OpenLoopView."""
    return OpenLoopView(
        id=row.id,
        user_id=row.user_id,
        content=row.content,
        status=row.status or "active",
        created_at=row.created_at,
        due_at=row.due_at,
        source_message=row.source_message,
        resolved_at=row.resolved_at,
        source="open_loops_legacy",
    )


async def read_open_loops_unified(
    session: Any,
    *,
    user_id: str,
    statuses: Iterable[str] | None = None,
    limit: int | None = None,
    content_terms: Iterable[str] | None = None,
) -> list[OpenLoopView]:
    """Read open loops, preferring attentions, falling back to legacy.

    Args:
        session: Active SQLAlchemy AsyncSession.
        user_id: Owner.
        statuses: Iterable of legacy status values to include
            (e.g. ``("active",)``). None = all statuses.
        limit: Final cap. Applied after merge.
        content_terms: Optional list of substrings; rows must contain at
            least one (case-insensitive). Applied after merge.

    Returns:
        List of OpenLoopView, freshest first, capped at ``limit``.
    """
    try:
        from sqlalchemy import or_, select

        from backend.db.models import AttentionRow, OpenLoop
    except Exception:
        logger.exception("read_open_loops_unified: imports failed")
        return []

    statuses_set = set(statuses) if statuses else None
    attn_target_statuses: set[str] | None = None
    if statuses_set:
        attn_target_statuses = set()
        for legacy in statuses_set:
            attn_target_statuses.update(_LEGACY_TO_ATTENTION_STATUS.get(legacy, []))

    # ----- Primary: attentions(card='open_loop') -----
    views: list[OpenLoopView] = []
    seen_legacy_ids: set[str] = set()
    try:
        stmt = (
            select(AttentionRow)
            .where(AttentionRow.user_id == user_id)
            .where(AttentionRow.card == _OPEN_LOOP_CARD)
            .order_by(AttentionRow.created_at.desc())
        )
        if attn_target_statuses is not None:
            stmt = stmt.where(AttentionRow.status.in_(list(attn_target_statuses)))
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            v = _attention_to_view(r)
            views.append(v)
            payload = r.payload or {}
            legacy_id = payload.get("mirror_open_loop_id") if isinstance(payload, dict) else None
            if legacy_id:
                seen_legacy_ids.add(str(legacy_id))
    except Exception:
        logger.exception("read_open_loops_unified: attentions read failed")

    # ----- Fallback: legacy rows that don't have a mirror -----
    try:
        legacy_stmt = (
            select(OpenLoop)
            .where(OpenLoop.user_id == user_id)
            .order_by(OpenLoop.created_at.desc())
        )
        if statuses_set:
            legacy_stmt = legacy_stmt.where(OpenLoop.status.in_(list(statuses_set)))
        if seen_legacy_ids:
            legacy_stmt = legacy_stmt.where(OpenLoop.id.notin_(list(seen_legacy_ids)))
        legacy_rows = (await session.execute(legacy_stmt)).scalars().all()
        for r in legacy_rows:
            views.append(_legacy_to_view(r))
    except Exception:
        logger.exception("read_open_loops_unified: legacy read failed")

    # ----- Merge sort + filter + cap -----
    views.sort(
        key=lambda v: v.created_at or datetime.min,
        reverse=True,
    )

    if content_terms:
        terms_lower = [t.lower() for t in content_terms if t]
        if terms_lower:
            views = [
                v for v in views
                if any(t in v.content.lower() for t in terms_lower)
            ]

    if limit is not None and limit > 0:
        views = views[:limit]

    return views
