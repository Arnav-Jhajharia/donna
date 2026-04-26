"""Postgres read/write helpers for ``dashboard_manifests``.

Two functions: ``upsert_manifest`` writes the latest plan, ``get_latest_manifest``
reads it back as a raw dict. Single row per user — no versioning.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.dashboard.manifest_events import publish as publish_manifest_change
from backend.dashboard.schema import DashboardPlan
from db.models import DashboardManifest
from db.session import async_session

logger = logging.getLogger(__name__)


async def upsert_manifest(
    user_id: str, plan: DashboardPlan, *, trigger: str | None = None
) -> None:
    """INSERT … ON CONFLICT (user_id) DO UPDATE.

    Always serializes with ``by_alias=True`` so the JSONB blob carries the
    same camelCase keys the TypeScript renderer expects.
    """
    payload = plan.model_dump(mode="json", by_alias=True, exclude_none=False)
    stmt = (
        pg_insert(DashboardManifest)
        .values(user_id=user_id, plan_jsonb=payload, trigger=trigger)
        .on_conflict_do_update(
            index_elements=[DashboardManifest.user_id],
            set_={
                "plan_jsonb": payload,
                "trigger": trigger,
            },
        )
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()
    # Fire SSE subscribers (in-process; harmless when none exist).
    publish_manifest_change(user_id)


async def get_latest_manifest(user_id: str) -> dict[str, Any] | None:
    """Return the raw plan_jsonb dict for ``user_id``, or None."""
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(DashboardManifest).where(
                        DashboardManifest.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception("get_latest_manifest: db error")
        return None
    return row.plan_jsonb if row is not None else None
