"""Dual-write mirror: open_loops → attentions(card='open_loop').

Phase 1a of the open_loops → attentions consolidation. Every write to
``open_loops`` also writes (or updates) a matching row in ``attentions``
with ``card='open_loop'``. The legacy ``open_loops`` table stays the
primary source until Phase 1c flips readers; this module just keeps the
shadow in sync so backfill and switchover are safe.

All operations are best-effort. The legacy ``open_loops`` write is the
authoritative one — if mirroring fails the caller still returns ok. The
mirror is used in Phase 1b (backfill) and Phase 1c (read switch) only;
nothing reads from ``attentions(card='open_loop')`` in production yet.

Cross-reference: ``payload['mirror_open_loop_id']`` carries the legacy
``open_loops.id`` so the two rows can be matched during migration.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_OPEN_LOOP_CARD = "open_loop"
_MIRROR_ORIGIN = "user_explicit"
_TITLE_MAX = 80


def _build_payload(
    *,
    open_loop_id: str,
    content: str,
    source_message: str | None,
    due_at: datetime | None,
) -> dict[str, Any]:
    """Assemble the AttentionRow.payload JSONB for an open-loop mirror."""
    return {
        "spec": {
            "card": _OPEN_LOOP_CARD,
            "subject": {
                "name": content[:_TITLE_MAX],
                "type": "open_loop_thread",
            },
            "rationale": content,
            "due_at": due_at.isoformat() if due_at else None,
        },
        "mirror_source": "open_loops",
        "mirror_open_loop_id": open_loop_id,
        "source_message": source_message,
    }


async def mirror_create_open_loop(
    session: Any,
    *,
    user_id: str,
    open_loop_id: str,
    content: str,
    source_message: str | None = None,
    due_at: datetime | None = None,
) -> str | None:
    """Insert an AttentionRow mirroring a newly-created open_loop.

    Returns the new attention_id on success, or None on best-effort
    failure (logged, never raised — the legacy write must succeed).
    The session must be the same one the caller used for the
    ``open_loops`` insert; commit happens at the caller boundary so the
    mirror is atomic with the primary.
    """
    try:
        from backend.db.models import AttentionRow

        title = content[:_TITLE_MAX]
        row = AttentionRow(
            user_id=user_id,
            title=title,
            card=_OPEN_LOOP_CARD,
            cadence_type="one_shot",
            origin=_MIRROR_ORIGIN,
            status="live",
            payload=_build_payload(
                open_loop_id=open_loop_id,
                content=content,
                source_message=source_message,
                due_at=due_at,
            ),
        )
        session.add(row)
        await session.flush()  # populate row.id without committing
        return row.id
    except Exception:
        logger.exception(
            "mirror_create_open_loop: failed for open_loop_id=%s user=%s",
            open_loop_id,
            user_id[:8] if user_id else "?",
        )
        return None


async def mirror_close_open_loop(
    session: Any,
    *,
    user_id: str,
    open_loop_id: str,
) -> bool:
    """Update the mirrored AttentionRow to status='resolved'.

    Returns True if a row was found and updated, False otherwise (no
    matching mirror, or best-effort failure). Caller commits.
    """
    try:
        from sqlalchemy import select, update

        from backend.db.models import AttentionRow

        result = await session.execute(
            select(AttentionRow.id)
            .where(
                AttentionRow.user_id == user_id,
                AttentionRow.card == _OPEN_LOOP_CARD,
                AttentionRow.payload["mirror_open_loop_id"].astext == open_loop_id,
            )
        )
        row_id = result.scalar_one_or_none()
        if row_id is None:
            return False
        await session.execute(
            update(AttentionRow)
            .where(AttentionRow.id == row_id)
            .values(status="resolved")
        )
        return True
    except Exception:
        logger.exception(
            "mirror_close_open_loop: failed for open_loop_id=%s user=%s",
            open_loop_id,
            user_id[:8] if user_id else "?",
        )
        return False
