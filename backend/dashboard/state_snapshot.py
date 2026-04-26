"""Per-user state snapshot for /observe.

Returns a single dict that captures everything that matters for "is
donna actually working for this user right now":

    user                 — name, phone, tz, last_active_at
    living_profile       — narrative + generated_at + yesterday_refreshed_at
    attentions           — every Attention row, grouped by status
    instances            — DonnaInstance rows (active trackers etc.)
    schedules            — pending DonnaSchedule fires
    observations         — last 10 observation rows
    open_loops           — active threads
    chat                 — last 5 messages

This is a STATE view, not an event view. /observe's existing event
stream answers "what happened in the last turn"; this answers "what is
true right now, across the whole system, for this user."

Best-effort: each section is independently fault-tolerant. A missing
DB connection or an unwritable file store yields ``[]`` for that
section, never a 500 — the caller still gets the rest of the snapshot.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)


_OBSERVATIONS_LIMIT = 10
_OPEN_LOOPS_LIMIT = 10
_SCHEDULES_LIMIT = 10
_CHAT_LIMIT = 5


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.astimezone(timezone.utc).isoformat()
        except Exception:
            return value.isoformat()
    return str(value)


async def _fetch_user(user_id: str) -> dict[str, Any] | None:
    from db.models import User
    from db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "name": getattr(row, "name", None),
        "phone": getattr(row, "phone", None),
        "timezone": getattr(row, "timezone", None),
        "last_active_at": _iso(getattr(row, "last_active_at", None)),
        "living_profile": getattr(row, "living_profile", None) or {},
    }


def _fetch_attentions(user_id: str) -> list[dict[str, Any]]:
    try:
        from donna.attention.noise import filter_attentions
        from donna.attention.store import AttentionStore
    except Exception:
        return []
    try:
        rows = AttentionStore().list(user_id=user_id)
    except Exception:
        logger.exception("state_snapshot: attentions fetch failed user=%s", user_id[:8])
        return []
    rows = filter_attentions(rows)
    out: list[dict[str, Any]] = []
    for a in rows:
        spec = a.spec
        out.append(
            {
                "id": str(a.id),
                "status": getattr(a.status, "value", str(a.status)),
                "origin": getattr(a.origin, "value", str(a.origin)),
                "card": getattr(spec.card, "value", str(spec.card)),
                "title": spec.title,
                "description": spec.description,
                "subject": getattr(getattr(spec, "subject", None), "name", None),
                "domain_tags": [
                    getattr(t, "value", str(t)) for t in (spec.domain_tags or [])
                ],
                "cadence_type": getattr(
                    spec.cadence.type, "value", str(spec.cadence.type)
                ),
                "created_at": _iso(getattr(a, "created_at", None)),
                "last_update_at": _iso(getattr(a, "last_update_at", None)),
                "update_count": getattr(a, "update_count", 0),
                "shadow_state": (
                    {
                        "tick_count": a.shadow_state.tick_count,
                        "promotion_hits": a.shadow_state.promotion_hits,
                        "max_ticks": a.shadow_state.max_ticks,
                    }
                    if getattr(a, "shadow_state", None)
                    else None
                ),
            }
        )
    return out


async def _fetch_instances(user_id: str) -> list[dict[str, Any]]:
    from db.models import DonnaInstance
    from db.session import async_session

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(DonnaInstance)
                    .where(DonnaInstance.user_id == user_id)
                    .order_by(DonnaInstance.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": r.id,
            "primitive": r.primitive,
            "connector": r.connector,
            "label": r.label,
            "status": r.status,
            "config": r.config or {},
            "used_count": r.used_count,
            "last_used_at": _iso(r.last_used_at),
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


async def _fetch_schedules(user_id: str, limit: int) -> list[dict[str, Any]]:
    from db.models import DonnaSchedule
    from db.session import async_session

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(DonnaSchedule)
                    .where(DonnaSchedule.user_id == user_id)
                    .order_by(DonnaSchedule.fire_at.asc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": r.id,
            "fire_at": _iso(r.fire_at),
            "status": r.status,
            "origin": r.origin,
            "fired": r.fired,
            "fired_at": _iso(r.fired_at),
            "attention_id": r.attention_id,
            "context": r.context or {},
        }
        for r in rows
    ]


async def _fetch_observations(user_id: str, limit: int) -> list[dict[str, Any]]:
    from db.models import Observation
    from db.session import async_session

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .order_by(Observation.event_time.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": r.id,
            "type": r.type,
            "event_time": _iso(r.event_time),
            "fields": r.fields or {},
            "raw": getattr(r, "raw", None),
        }
        for r in rows
    ]


async def _fetch_open_loops(user_id: str, limit: int) -> list[dict[str, Any]]:
    from db.models import OpenLoop
    from db.session import async_session
    from donna.attention.noise import filter_open_loops

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(OpenLoop)
                    .where(OpenLoop.user_id == user_id)
                    .where(OpenLoop.status == "active")
                    .order_by(OpenLoop.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    rows = filter_open_loops(list(rows))
    return [
        {
            "id": r.id,
            "content": r.content,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


async def _fetch_chat(user_id: str, limit: int) -> list[dict[str, Any]]:
    from db.models import ChatMessage
    from db.session import async_session

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "role": r.role,
            "content": r.content,
            "created_at": _iso(r.created_at),
            "is_proactive": getattr(r, "is_proactive", False),
        }
        for r in reversed(list(rows))
    ]


async def gather_state(user_id: str) -> dict[str, Any]:
    """Single-call snapshot for /observe.

    Each subsection fails closed (returns ``[]`` on error) so a partial
    result still renders. The caller is expected to cope with missing
    sections.
    """
    user = await _fetch_user(user_id)
    if user is None:
        return {
            "user_id": user_id,
            "user": None,
            "fetched_at": _iso(datetime.now(timezone.utc)),
        }

    # File-store reads are sync; everything else is async.
    attentions = _fetch_attentions(user_id)

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            logger.exception("state_snapshot: subsection failed user=%s", user_id[:8])
            return []

    instances, schedules, observations, open_loops, chat = await asyncio.gather(
        _safe(_fetch_instances(user_id)),
        _safe(_fetch_schedules(user_id, _SCHEDULES_LIMIT)),
        _safe(_fetch_observations(user_id, _OBSERVATIONS_LIMIT)),
        _safe(_fetch_open_loops(user_id, _OPEN_LOOPS_LIMIT)),
        _safe(_fetch_chat(user_id, _CHAT_LIMIT)),
    )

    return {
        "user_id": user_id,
        "user": user,
        "attentions": attentions,
        "instances": instances,
        "schedules": schedules,
        "observations": observations,
        "open_loops": open_loops,
        "chat": chat,
        "fetched_at": _iso(datetime.now(timezone.utc)),
    }
