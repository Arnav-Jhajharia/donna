"""Dispatch feature manifest hooks (``post_observation`` / ``post_turn``).

A feature manifest declares hook bindings as ``(event, handler_name)``
strings. The handler functions are registered at boot via
``backend.features.handlers.register_hook_handler``. This module is the
fan-out: given a user + an event, walk the user's active features and
call each registered handler in order.

The dispatcher is **best-effort** — handler failures are logged and
swallowed so they never block the calling write path. Feature handlers
that need transactional guarantees must own their own transactions; the
dispatcher hands them the same DB session and the inbound payload, no
more.

Phase 4 scope: ``post_observation`` is called from
``log_observation`` AFTER the row + auto-tagging are committed.
``post_turn`` will be wired into the post-turn hook bus when Phase 4b
lands the broader plumbing.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Feature

logger = logging.getLogger(__name__)


async def dispatch_post_observation(
    *,
    session: AsyncSession,
    user_id: str,
    obs: Any,
) -> int:
    """Dispatch ``post_observation`` for every matching active feature.

    A feature matches if any of its ``manifest.observations[*].type``
    equals ``obs.type`` (regardless of owner — both primary owners and
    subscriber features get the event). The dispatcher does NOT scope
    by ``obs.feature_id`` because subscriber features need to react to
    primary-owner writes.

    Returns the count of handlers invoked. Failures inside individual
    handlers don't decrement the count — we count attempted dispatches
    so observability can detect missed registrations distinctly from
    handler errors.
    """
    try:
        from backend.features.handlers import (
            get_hook_handler,
            is_hook_handler_registered,
        )
        from backend.features.registry import get_registry
    except Exception:
        logger.exception(
            "feature hook dispatcher: feature subsystem unavailable"
        )
        return 0

    try:
        rows = (
            await session.execute(
                select(Feature).where(
                    Feature.user_id == user_id,
                    Feature.status == "active",
                )
            )
        ).scalars().all()
    except Exception:
        logger.exception(
            "feature hook dispatcher: feature read failed user=%s", user_id
        )
        return 0
    if not rows:
        return 0

    registry = get_registry()
    obs_type = getattr(obs, "type", None)
    if not obs_type:
        return 0

    invoked = 0
    for feature in rows:
        if not feature.template_id:
            continue
        manifest = registry.get_template(feature.template_id)
        if manifest is None:
            continue
        feature_owns_type = any(
            d.type == obs_type for d in manifest.observations
        )
        if not feature_owns_type:
            continue
        for hook in manifest.hooks:
            if hook.event != "post_observation":
                continue
            if not is_hook_handler_registered(hook.handler):
                logger.debug(
                    "feature hook %s.%s: skipped (handler %r not registered)",
                    feature.template_id,
                    hook.event,
                    hook.handler,
                )
                continue
            handler = get_hook_handler(hook.handler)
            try:
                await handler(
                    session=session,
                    user_id=user_id,
                    feature=feature,
                    obs=obs,
                )
                invoked += 1
            except Exception:
                logger.exception(
                    "feature hook %s.%s handler %r raised",
                    feature.template_id,
                    hook.event,
                    hook.handler,
                )
    return invoked
