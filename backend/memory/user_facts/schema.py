"""Typed schema for canonical user facts (Living Profile sub-store).

Facts are stored as JSONB dict on User.facts keyed by FactKey. Values are
UserFact entries: {value, source, confidence, updated_at}.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TypedDict


class FactKey(str, Enum):
    PREFERRED_NAME = "preferred_name"
    HOME_CITY = "home_city"
    CURRENT_CITY = "current_city"
    HOME_TIMEZONE = "home_timezone"
    CURRENT_TIMEZONE = "current_timezone"
    PROFESSION = "profession"
    AGE_GROUP = "age_group"
    LIFE_STAGE = "life_stage"
    HOUSEHOLD = "household"
    PRIMARY_LANGUAGE = "primary_language"
    WAKE_TIME = "wake_time"
    SLEEP_TIME = "sleep_time"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Source(str, Enum):
    DEFAULT = "default"
    ONBOARDING_EXPLICIT = "onboarding_explicit"
    CONVERSATION_EXTRACTED = "conversation_extracted"
    CONVERSATION_INFERRED = "conversation_inferred"
    USER_CORRECTION = "user_correction"
    OBSERVED_BEHAVIOR = "observed_behavior"


class UserFact(TypedDict):
    value: str
    source: str
    confidence: str
    updated_at: str


_CONFIDENCE_ORDER = [Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]
_SOURCE_ORDER = [
    Source.DEFAULT,
    Source.CONVERSATION_INFERRED,
    Source.OBSERVED_BEHAVIOR,
    Source.CONVERSATION_EXTRACTED,
    Source.ONBOARDING_EXPLICIT,
    Source.USER_CORRECTION,
]


def confidence_rank(c: str) -> int:
    try:
        return _CONFIDENCE_ORDER.index(Confidence(c))
    except ValueError:
        return -1


def source_rank(s: str) -> int:
    try:
        return _SOURCE_ORDER.index(Source(s))
    except ValueError:
        return -1


def is_valid_fact_key(key: str) -> bool:
    try:
        FactKey(key)
        return True
    except ValueError:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def DEFAULT_FACTS() -> dict[str, UserFact]:
    return {
        FactKey.PRIMARY_LANGUAGE.value: {
            "value": "en",
            "source": Source.DEFAULT.value,
            "confidence": Confidence.MEDIUM.value,
            "updated_at": _now_iso(),
        },
    }
