"""Schema enforcer — fills missing fields on observations based on live attentions.

When a meal observation lands, this module:
  1. Looks up live tally attentions for the user whose ``sources.params.tag``
     matches this observation type (meal_calories matches type=meal, etc.).
  2. For each match, ensures ``fields[required_key]`` is populated. Today
     the only enforced key is ``calories`` for meal observations — the
     calorie estimator (lookup table + Haiku fallback) fills it.
  3. Returns the merged fields dict so the caller can write it.

Generalizing later:
  - sleep_hours → estimate from raw text
  - expense → parse amount from raw if not supplied
  - water → infer count of glasses

For now, only the meal/calorie path is wired. Everything else falls
through unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def enforce_observation_schema(
    *,
    user_id: str,
    obs_type: str,
    fields: dict[str, Any],
    raw: str | None = None,
) -> dict[str, Any]:
    """Return a possibly-enriched fields dict.

    Best-effort. On any failure returns ``fields`` unchanged.
    """
    if not fields:
        fields = {}

    if obs_type == "meal" and "calories" not in fields:
        merged = await _enrich_meal_calories(fields=fields, raw=raw)
        if merged is not None:
            return merged

    return fields


async def _enrich_meal_calories(
    *, fields: dict[str, Any], raw: str | None
) -> dict[str, Any] | None:
    """Fill ``calories`` and ``calorie_confidence`` if we can estimate."""
    try:
        from backend.memory.observations.calorie_estimator import (
            estimate_calories,
        )
    except Exception:
        logger.exception("schema_enforcer: estimator import failed")
        return None

    item = (fields.get("item") or "").strip() or (raw or "").strip()
    if not item:
        return None
    try:
        kcal, confidence = estimate_calories(item)
    except Exception:
        logger.exception("schema_enforcer: estimator raised for %r", item)
        return None
    if kcal is None:
        return None
    out = dict(fields)
    out["calories"] = kcal
    out["calorie_confidence"] = confidence
    return out
