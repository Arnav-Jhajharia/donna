"""Formats fact-change observations. JSONB is canonical; this is a stub
kept for API compatibility with the source port.
"""
from __future__ import annotations

import logging

from backend.memory.user_facts.schema import Source

logger = logging.getLogger(__name__)

_KEY_LABELS = {
    "preferred_name": "preferred name",
    "home_city": "home city",
    "current_city": "current city",
    "home_timezone": "home timezone",
    "current_timezone": "current timezone",
    "profession": "profession",
    "age_group": "age group",
    "life_stage": "life stage",
    "household": "household",
    "primary_language": "primary language",
}


def format_fact_observation(key: str, value: str, source: Source, confidence) -> str:
    label = _KEY_LABELS.get(key, key.replace("_", " "))
    if source == Source.ONBOARDING_EXPLICIT:
        return f"User told me in onboarding their {label} is: {value}"
    if source == Source.USER_CORRECTION:
        return f"User corrected their {label}: {value}"
    if source == Source.CONVERSATION_EXTRACTED:
        return f"User mentioned their {label} in conversation: {value}"
    if source == Source.CONVERSATION_INFERRED:
        return f"I inferred from conversation that their {label} is: {value}"
    if source == Source.OBSERVED_BEHAVIOR:
        return f"Based on observed behavior, their {label} is: {value}"
    return f"User's {label}: {value}"


async def write_fact_observation(**kwargs) -> None:
    logger.debug("write_fact_observation: no-op (JSONB canonical)")
