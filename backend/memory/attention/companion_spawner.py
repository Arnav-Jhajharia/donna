"""Companion attention spawner.

When the proposer creates a primary attention (e.g. a tally for "track my
calories"), this module proposes sibling attentions that complete the
product feature. Today's mappings:

  - ``card=tally`` + meal-related subject → lunch + dinner ping
    reminders to log meals
  - ``card=tally`` + sleep subject        → wind-down ping ~1h before
    user's ``sleep_time``
  - ``card=tally`` + spend subject        → end-of-day "log spend" ping

Companions are created with ``status=shadow`` so they don't immediately
fire on the user. A separate promotion path can flip them to ``live``
once the user shows engagement with the primary attention.

Best-effort: failures here never block primary creation. The companion
list is small + curated; we extend as patterns emerge.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_MEAL_PATTERNS = re.compile(
    r"calorie|meal|food|eating|nutrition|diet|weight",
    re.IGNORECASE,
)
_SLEEP_PATTERNS = re.compile(r"sleep|rest|bedtime", re.IGNORECASE)
_SPEND_PATTERNS = re.compile(r"spend|expense|budget|money", re.IGNORECASE)
_HYDRATION_PATTERNS = re.compile(r"water|hydrat|drink", re.IGNORECASE)


def companion_specs_for(primary_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return companion AttentionSpec dicts to propose alongside the primary.

    ``primary_spec`` is the dict form of the AttentionSpec just created.
    Returns 0+ companion specs. Each is a complete AttentionSpec dict
    ready to be wrapped in an Attention and stored.
    """
    if not isinstance(primary_spec, dict):
        return []
    card = (primary_spec.get("card") or "").lower()
    if card != "tally":
        return []

    subject = primary_spec.get("subject") or {}
    subject_name = (subject.get("name") if isinstance(subject, dict) else "") or ""
    title = primary_spec.get("title") or ""
    description = primary_spec.get("description") or ""
    blob = f"{subject_name} {title} {description}".lower()

    companions: list[dict[str, Any]] = []
    if _MEAL_PATTERNS.search(blob):
        companions.extend(_meal_companions(primary_spec))
    elif _SLEEP_PATTERNS.search(blob):
        companions.extend(_sleep_companions(primary_spec))
    elif _SPEND_PATTERNS.search(blob):
        companions.extend(_spend_companions(primary_spec))
    elif _HYDRATION_PATTERNS.search(blob):
        companions.extend(_hydration_companions(primary_spec))
    return companions


def _ping(
    *,
    title: str,
    subject_name: str,
    cron: str,
    nudge_text: str,
    domain_tags: list[str],
) -> dict[str, Any]:
    """Build a minimal PING AttentionSpec dict."""
    return {
        "card": "ping",
        "title": title,
        "description": nudge_text,
        "subject": {"name": subject_name, "type": "self"},
        "domain_tags": domain_tags,
        "sources": [
            {"type": "internal_observations", "params": {"tag": subject_name}}
        ],
        "extractor": {"prompt": "(no extraction; this is a time-based reminder)"},
        "cadence": {"type": "scheduled", "params": {"cron": cron}},
        "surface_policy": {
            "default": "notify",
            "escalations": [],
            "nudge_policy": {
                "if_silent_for_seconds": 86400,
                "nudge_via": "whatsapp",
                "nudge_text": nudge_text,
            },
            "quiet_hours_respected": True,
        },
        "relevance_threshold": 0.5,
        "dedup": {"key": "id", "window_size": 50},
    }


def _meal_companions(primary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _ping(
            title="log your lunch",
            subject_name="lunch log reminder",
            cron="0 13 * * *",  # 1pm user-local
            nudge_text="quick — what did you have for lunch?",
            domain_tags=["health", "habit"],
        ),
        _ping(
            title="log your dinner",
            subject_name="dinner log reminder",
            cron="0 20 * * *",  # 8pm user-local
            nudge_text="dinner check — what did you eat?",
            domain_tags=["health", "habit"],
        ),
    ]


def _sleep_companions(primary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _ping(
            title="wind down",
            subject_name="wind down reminder",
            cron="0 22 * * *",  # 10pm user-local
            nudge_text="wind down soon — body holds the timing better when you start now.",
            domain_tags=["health", "habit"],
        ),
    ]


def _spend_companions(primary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _ping(
            title="log today's spend",
            subject_name="spend log reminder",
            cron="0 21 * * *",  # 9pm user-local
            nudge_text="end of day — anything you spent today worth logging?",
            domain_tags=["money", "habit"],
        ),
    ]


def _hydration_companions(primary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _ping(
            title="hydration check",
            subject_name="hydration ping",
            cron="0 11 * * *",  # 11am user-local
            nudge_text="water break — how many glasses today?",
            domain_tags=["health", "habit"],
        ),
        _ping(
            title="afternoon hydration",
            subject_name="hydration afternoon",
            cron="0 16 * * *",  # 4pm user-local
            nudge_text="afternoon hydration check — top up if you're under.",
            domain_tags=["health", "habit"],
        ),
    ]


async def spawn_companions(
    *, user_id: str, primary_attention_id: str, primary_spec: dict[str, Any]
) -> list[str]:
    """Create companion attentions in the store. Returns ids created.

    Companions go in as ``status=shadow`` so they don't fire until the
    user accepts (or auto-promotion logic flips them).
    """
    specs = companion_specs_for(primary_spec)
    if not specs:
        return []
    ids_created: list[str] = []
    try:
        from donna.attention.schema import (
            Attention,
            AttentionOrigin,
            AttentionStatus,
            AttentionSpec,
        )
        from donna.attention.store import AttentionStore

        store = AttentionStore()
    except Exception:
        logger.exception("companion_spawner: imports failed")
        return []

    for spec_dict in specs:
        try:
            spec = AttentionSpec.model_validate(spec_dict)
            attention = Attention(
                user_id=user_id,
                spec=spec,
                origin=AttentionOrigin.SHADOW_INFERRED,
                status=AttentionStatus.SHADOW,
                parent_attention_id=primary_attention_id,
            )
            store.put(attention)
            ids_created.append(str(attention.id))
            logger.info(
                "companion_spawner: spawned shadow id=%s parent=%s title=%r",
                str(attention.id)[:8],
                primary_attention_id[:8],
                spec.title,
            )
        except Exception:
            logger.exception(
                "companion_spawner: spawn failed parent=%s title=%r",
                primary_attention_id[:8],
                spec_dict.get("title"),
            )
    return ids_created
