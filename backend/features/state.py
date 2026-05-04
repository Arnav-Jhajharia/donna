"""Read/write helpers for the ``features.state`` JSONB column.

The ``state`` column carries the running values used by the dashboard
renderer (today_count, streak_days, last_logged_at). The shape is
feature-specific — Phase 1 doesn't impose a schema. Helpers here keep
callers from having to hand-write JSONB upserts.

All helpers are async to match the rest of the postgres-backed code
(``backend.db.session.async_session``).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_feature_state(
    *, user_id: str, template_id: str
) -> dict[str, Any] | None:
    """Return the live state for a user's installed feature.

    Returns ``None`` if the user does not have the feature installed.
    Does not raise on missing rows — callers expect the feature may not
    be active (a free-form observation flow is the common case).
    """
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(Feature).where(
                    Feature.user_id == user_id,
                    Feature.template_id == template_id,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    state = row.state
    return state if isinstance(state, dict) else {}


async def update_feature_state(
    *, feature_id: str, **patches: Any
) -> bool:
    """Merge ``patches`` into the feature's ``state`` JSONB.

    Returns ``True`` on a successful update, ``False`` if the row was
    not found. The merge is shallow — passing ``today_count=3`` overwrites
    the top-level key but leaves siblings untouched. Nested merges are
    the caller's responsibility (no surprise side-effects on deeply
    nested aggregation results).
    """
    if not patches:
        return False

    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(Feature).where(Feature.id == feature_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        current = row.state if isinstance(row.state, dict) else {}
        row.state = {**current, **patches}
        await session.commit()
    return True


async def get_feature_config(
    *, user_id: str, template_id: str
) -> dict[str, Any] | None:
    """Return the live config for a user's installed feature.

    Sibling helper to ``get_feature_state``. Configs change less often
    than state but the read shape is the same.
    """
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(Feature).where(
                    Feature.user_id == user_id,
                    Feature.template_id == template_id,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    config = row.config
    return config if isinstance(config, dict) else {}
