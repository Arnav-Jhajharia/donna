"""Zero-LLM fact extraction from explicit user correction phrases.

Runs pre-BRAIN (before the USER MODEL block is rendered) so corrections land
in the same turn the user made them. This is the fast, precise path for the
handful of patterns humans actually use to state or correct identity facts.

The Haiku extractor in `extract_user_facts.py` still runs post-turn for the
implicit / vague cases that don't match these regex patterns.

Covered patterns (all require first-person; third-party mentions are rejected
via the same subject-safety filter used by the LLM extractor):

    "my name is <X>"            → preferred_name
    "call me <X>"               → preferred_name
    "actually i'm <X>"          → preferred_name (correction)
    "i'm a/an <X>"              → profession
    "i work as <X>"             → profession
    "i live in <X>"             → current_city
    "i'm in <X>"                → current_city
    "i moved to <X>"            → current_city (correction)
    "i'm from <X>"              → home_city
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from backend.memory.hooks.extract_user_facts import (
    _message_is_first_person_about_self,
)
from backend.memory.user_facts.api import update_user_fact
from backend.memory.user_facts.schema import Confidence, FactKey, Source

logger = logging.getLogger(__name__)

# Value capture stops at conjunctions/fillers so "my name is arnav btw not aayam"
# extracts "arnav", not the whole trailing clause.
_VALUE_STOPWORDS = (
    r"btw|by\s+the\s+way|not|actually|instead|rather|just|tbh|though|"
    r"honestly|really|seriously|anyway|anymore|now|today|lol|haha|etc"
)

# Generic value: one to four non-stopword tokens of letters/apostrophes/hyphens/spaces.
# Up to 4 tokens covers "new york city" or "san francisco" without sucking in whole clauses.
_VALUE = rf"([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){{0,3}})"

# Pattern table: (regex, fact_key, is_correction_hint)
# Each regex must have exactly one capture group producing the raw value.
_PATTERNS: tuple[tuple[re.Pattern[str], FactKey, bool], ...] = (
    # name — declarations
    (
        re.compile(rf"\bmy\s+name\s+is\s+{_VALUE}", re.IGNORECASE),
        FactKey.PREFERRED_NAME,
        True,  # "my name is X" is a statement of truth; treat as correction-grade
    ),
    (
        re.compile(rf"\bcall\s+me\s+{_VALUE}", re.IGNORECASE),
        FactKey.PREFERRED_NAME,
        True,
    ),
    (
        re.compile(rf"\bactually\s+(?:i'?m|im)\s+{_VALUE}", re.IGNORECASE),
        FactKey.PREFERRED_NAME,
        True,
    ),
    # profession
    (
        re.compile(rf"\b(?:i'?m|im|i\s+am)\s+an?\s+{_VALUE}", re.IGNORECASE),
        FactKey.PROFESSION,
        False,
    ),
    (
        re.compile(rf"\bi\s+work\s+as\s+an?\s+{_VALUE}", re.IGNORECASE),
        FactKey.PROFESSION,
        False,
    ),
    # current city
    (
        re.compile(rf"\bi\s+(?:live|moved|relocated)\s+(?:in|to)\s+{_VALUE}", re.IGNORECASE),
        FactKey.CURRENT_CITY,
        False,
    ),
    (
        re.compile(rf"\b(?:i'?m|im|i\s+am)\s+(?:now\s+)?in\s+{_VALUE}", re.IGNORECASE),
        FactKey.CURRENT_CITY,
        False,
    ),
    # home city
    (
        re.compile(rf"\bi'?m\s+from\s+{_VALUE}", re.IGNORECASE),
        FactKey.HOME_CITY,
        False,
    ),
)


@dataclass(frozen=True)
class DetectedFact:
    key: FactKey
    value: str
    is_correction: bool
    matched_pattern: str


def _clean_value(raw: str) -> str:
    """Strip trailing stopwords, punctuation, and excess whitespace."""
    value = raw.strip().strip(",.!?;:\"'")
    # Strip trailing stopword tokens (e.g. "arnav btw" -> "arnav")
    stop_re = re.compile(rf"\s+(?:{_VALUE_STOPWORDS})\b.*$", re.IGNORECASE)
    value = stop_re.sub("", value)
    return value.strip()


def detect_facts(message: str) -> list[DetectedFact]:
    """Scan `message` for explicit fact declarations. Returns empty list on
    any third-party mention or no-match case.
    """
    if not message.strip():
        return []
    # Subject-safety: reject outright if the message names a third party.
    if not _message_is_first_person_about_self(message):
        return []

    found: list[DetectedFact] = []
    seen_keys: set[FactKey] = set()
    for pattern, key, correction_hint in _PATTERNS:
        if key in seen_keys:
            continue
        match = pattern.search(message)
        if not match:
            continue
        raw = match.group(1)
        value = _clean_value(raw)
        if not value or len(value) > 60:
            continue
        found.append(
            DetectedFact(
                key=key,
                value=value,
                is_correction=correction_hint,
                matched_pattern=pattern.pattern,
            )
        )
        seen_keys.add(key)
    return found


async def apply_detected_facts(
    user_id: str, facts: Iterable[DetectedFact]
) -> list[DetectedFact]:
    """Persist each detected fact via update_user_fact. Returns the list that
    was actually written (de-duped, errors swallowed).
    """
    written: list[DetectedFact] = []
    for fact in facts:
        source = Source.USER_CORRECTION if fact.is_correction else Source.CONVERSATION_EXTRACTED
        try:
            await update_user_fact(
                user_id=user_id,
                key=fact.key.value,
                value=fact.value,
                source=source,
                confidence=Confidence.HIGH,
            )
            written.append(fact)
            logger.info(
                "deterministic_fact_detector: wrote %s=%r user=%s correction=%s",
                fact.key.value, fact.value, user_id[:8], fact.is_correction,
            )
        except Exception:
            logger.exception(
                "deterministic_fact_detector: write failed user=%s key=%s",
                user_id[:8], fact.key.value,
            )
    return written


async def run(user_id: str, inbound: str) -> list[DetectedFact]:
    """One-shot pre-BRAIN entry point. Detect + persist in one call."""
    if not user_id or not inbound:
        return []
    detected = detect_facts(inbound)
    if not detected:
        return []
    return await apply_detected_facts(user_id, detected)
