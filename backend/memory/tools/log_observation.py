"""log_observation — record a countable event."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from backend.memory.time import coerce_to_utc_naive
from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Log a countable/measurable user event (meal, expense, mood, habit, sleep, etc.). "
    "Model decides when something the user said is worth tracking as structured data."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "fields": {"type": "object"},
        "tags": {"type": "object"},
        "raw": {"type": "string"},
        "event_time": {"type": "string", "description": "Optional ISO timestamp for when the event happened."},
        "confidence": {"type": "number", "default": 1.0},
    },
    "required": ["type", "fields"],
}


@instrument_memory_op("postgres.observations")
async def log_observation(
    user_id: str,
    type: str,
    fields: dict,
    tags: dict | None = None,
    raw: str | None = None,
    event_time: datetime | str | None = None,
    confidence: float = 1.0,
) -> ToolResult:
    try:
        from sqlalchemy import select

        from backend.db.models import DonnaInstance, Observation, User
        from backend.db.session import async_session
    except Exception:
        return degraded("db unavailable")
    try:
        # Schema enforcer: fill domain-specific fields (e.g. calories for
        # meal observations) BEFORE the row is written. Best-effort.
        try:
            from backend.memory.observations.schema_enforcer import (
                enforce_observation_schema,
            )

            fields = await enforce_observation_schema(
                user_id=user_id, obs_type=type, fields=fields, raw=raw
            )
        except Exception:
            logger.exception("log_observation: schema enforcer raised")

        async with async_session() as session:
            user = (
                await session.execute(
                    select(User).where(User.id == user_id)
                )
            ).scalar_one_or_none()
            timezone_name = user.timezone if user else None
            result = await session.execute(
                select(DonnaInstance).where(
                    DonnaInstance.user_id == user_id,
                    DonnaInstance.primitive == "track",
                    DonnaInstance.connector == "whatsapp_manual",
                    DonnaInstance.label == type,
                )
            )
            instance = result.scalar_one_or_none()
            if instance is None:
                instance = DonnaInstance(
                    user_id=user_id,
                    primitive="track",
                    connector="whatsapp_manual",
                    label=type,
                    config={"type": type},
                    status="active",
                )
                session.add(instance)
                await session.flush()
            # Phase 1 features tagging: if this user has an active feature
            # whose primary observation type matches, auto-tag the row
            # with the owning feature_id. Untagged free-form observations
            # stay NULL (backwards compatible with the entire pre-feature
            # observation history).
            feature_id = await _resolve_feature_id(
                session=session, user_id=user_id, obs_type=type
            )
            obs = Observation(
                user_id=user_id,
                instance_id=instance.id,
                type=type,
                fields=fields,
                tags=tags or {},
                raw=raw,
                event_time=_coerce_event_time(event_time, timezone_name),
                confidence=confidence,
                feature_id=feature_id,
            )
            session.add(obs)
            await session.commit()
            await session.refresh(obs)
            refreshed = await _refresh_situation_brief(user_id)

            # Trigger the attention runtime: re-evaluate live attentions
            # whose source matches this observation type. Tally rollups
            # update inline; pings/open_loops are evaluated for state
            # snapshots. Best-effort — failures here never block the write.
            await _reevaluate_attentions(user_id=user_id, obs_type=type)

            return ok({"id": obs.id, "type": obs.type, "situation_brief_refreshed": refreshed})
    except Exception as exc:
        logger.exception("log_observation failed")
        return degraded(f"db error: {exc}")


async def _resolve_feature_id(
    *, session, user_id: str, obs_type: str
) -> str | None:
    """Find the feature_id of an active feature claiming ``obs_type``.

    Returns ``None`` if (a) the type isn't owned by any system feature,
    (b) the user hasn't installed the owning feature, or (c) the feature
    subsystem is unavailable. ``None`` is the legitimate, backwards-
    compatible value for untagged free-form observations.

    Reads from the in-process feature registry (cheap) followed by a
    single query against the user's installed features (one row per
    template at most, indexed on ``user_id``).
    """
    try:
        from sqlalchemy import select

        from backend.db.models import Feature
        from backend.features.registry import get_registry
    except Exception:
        return None

    try:
        registry = get_registry()
    except Exception:
        logger.exception("log_observation: feature registry init failed")
        return None

    match = registry.manifest_for_observation(
        user_id=user_id, obs_type=obs_type
    )
    if match is None:
        return None
    _, template_id = match

    try:
        row = (
            await session.execute(
                select(Feature).where(
                    Feature.user_id == user_id,
                    Feature.template_id == template_id,
                    Feature.status == "active",
                )
            )
        ).scalar_one_or_none()
    except Exception:
        logger.exception(
            "log_observation: feature row lookup failed user=%s type=%s",
            user_id[:8] if user_id else "?",
            obs_type,
        )
        return None
    return row.id if row else None


async def _reevaluate_attentions(*, user_id: str, obs_type: str) -> None:
    """Best-effort: re-run the attention engine for cards likely impacted.

    Today: any new observation triggers a full sweep of LIVE tally
    attentions (cheap; deterministic sums). open_loop and event_stream
    don't need a re-eval per observation. Future iterations can narrow
    by tag.
    """
    try:
        from backend.memory.attention.engine import evaluate_user_attentions

        await evaluate_user_attentions(
            user_id=user_id,
            card_filter=("tally",),
            trigger=f"observation:{obs_type}",
        )
    except Exception:
        logger.exception(
            "log_observation: attention re-eval failed user=%s", user_id[:8]
        )


async def _refresh_situation_brief(user_id: str) -> bool:
    try:
        from backend.memory.tools.refresh_situation_brief import refresh_situation_brief_best_effort

        return await refresh_situation_brief_best_effort(user_id)
    except Exception:
        logger.exception("log_observation: situation brief refresh failed")
        return False


def _coerce_event_time(value: Any, timezone_name: str | None = None) -> datetime:
    return coerce_to_utc_naive(value, timezone_name)
