"""Post-turn dashboard refresh hook.

Donna's dashboard manifest only refreshed before this when:
  * the model called the ``update_dashboard`` tool (rare)
  * the user tapped Accept/Dismiss/Done on a tile

Result: a user could WhatsApp Donna five times across an afternoon and
the dashboard's hero would still say "Morning". Stale enough to break
the "she's holding your life" promise.

This hook fires after every reactive ``send_burst`` turn. If the latest
manifest is older than the debounce window (default 10 min), it kicks
off a fire-and-forget recompose. Idempotent: concurrent turns can't
double-fire because the upsert at the end overwrites whichever finishes
last.

Cost shape: ``compose_manifest`` is an LLM call (Sonnet 4.6), so the
debounce keeps per-user spend bounded — at most ~6 recomposes/hour
during heavy chat.

Tunable via ``DONNA_DASHBOARD_REFRESH_MIN_AGE_S`` (default 600s).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def _min_age_seconds() -> int:
    """Read the debounce window from env. Anything <60s is clamped to
    avoid pathological refresh loops if someone fat-fingers the var."""
    try:
        raw = int(os.getenv("DONNA_DASHBOARD_REFRESH_MIN_AGE_S", "600"))
    except ValueError:
        raw = 600
    return max(60, raw)


_pending_refreshes: set[asyncio.Task[Any]] = set()


async def run(ctx: Mapping[str, Any]) -> None:
    user_id = ctx.get("user_id")
    if not user_id:
        return

    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import DashboardManifest
    except Exception:
        logger.exception("refresh_dashboard: imports failed")
        return

    try:
        async with async_session() as s:
            existing = (
                await s.execute(
                    select(DashboardManifest).where(
                        DashboardManifest.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception(
            "refresh_dashboard: read failed user=%s", user_id[:8]
        )
        return

    min_age_s = _min_age_seconds()
    if existing is not None and existing.generated_at is not None:
        age = datetime.utcnow() - existing.generated_at
        if age < timedelta(seconds=min_age_s):
            return  # within debounce window — skip

    # Spawn a fire-and-forget recompose. Don't await — the user's reply
    # already shipped on WhatsApp; the dashboard refresh runs in the
    # background and lands by next poll.
    try:
        task = asyncio.create_task(
            _do_refresh(user_id),
            name=f"dashboard_refresh:{str(user_id)[:8]}",
        )
    except RuntimeError:
        return
    _pending_refreshes.add(task)
    task.add_done_callback(_pending_refreshes.discard)


async def _do_refresh(user_id: str) -> None:
    try:
        from backend.dashboard.compose import compose_manifest
        from backend.dashboard.store import upsert_manifest
    except Exception:
        logger.exception("refresh_dashboard: compose imports failed")
        return
    try:
        plan = await compose_manifest(user_id=user_id, trigger="post_turn")
    except Exception:
        logger.exception(
            "refresh_dashboard: compose raised user=%s", user_id[:8]
        )
        return
    if plan is None:
        return
    try:
        await upsert_manifest(user_id, plan, trigger="post_turn")
    except Exception:
        logger.exception(
            "refresh_dashboard: upsert raised user=%s", user_id[:8]
        )
