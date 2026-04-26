"""Haiku subagent that extracts canonical user facts and writes via
update_user_fact (spec §6).

Also runs a cheap offline language detector on every turn so
primary_language upgrades from the default seed.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured
from backend.memory.user_facts.api import update_user_fact
from backend.memory.user_facts.language import detect_language
from backend.memory.user_facts.schema import Confidence, FactKey, Source, is_valid_fact_key

logger = logging.getLogger(__name__)

_MAX_EXTRACTIONS = 3
_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "synthesis" / "prompts" / "user_facts_extractor.md"
)

# Identity-shaped fact keys where writing the wrong subject is costly.
# For these we require a first-person marker in the inbound message and
# reject any extraction that co-occurs with third-party markers.
_IDENTITY_KEYS = frozenset(
    {
        FactKey.PREFERRED_NAME.value,
        FactKey.PROFESSION.value,
        FactKey.HOME_CITY.value,
        FactKey.CURRENT_CITY.value,
        FactKey.AGE_GROUP.value,
        FactKey.LIFE_STAGE.value,
        FactKey.HOUSEHOLD.value,
    }
)

# First-person markers the user would use when describing themselves.
_FIRST_PERSON_RE = re.compile(
    r"\b(i|i'?m|i'?ve|i'?d|i'?ll|my|myself|me|mine|call me)\b",
    re.IGNORECASE,
)

# Third-party markers indicating the message is about someone else.
# "my friend / coworker / ..." always denotes another person; "my" alone is
# first-person ("my job", "my home") so these must be multi-token patterns.
_THIRD_PARTY_RE = re.compile(
    r"\b(?:"
    r"my\s+(?:friend|friends|buddy|pal|mate|mentor|manager|boss|partner|colleague|colleagues|"
    r"coworker|coworkers|teammate|teammates|client|customer|investor|advisor|cofounder|"
    r"co-founder|founder|classmate|roommate|neighbor|neighbour|cousin|uncle|aunt|brother|"
    r"sister|sibling|parent|parents|mom|mum|dad|father|mother|son|daughter|kid|kids|"
    r"husband|wife|girlfriend|boyfriend|ex|date|crush)"
    r"|his|her|their|he\s+is|she\s+is|they\s+are|he'?s|she'?s|they'?re"
    r"|just\s+met|i\s+met|met\s+\w+\s+(?:from|at|in)"
    r")\b",
    re.IGNORECASE,
)


def _message_is_first_person_about_self(message: str) -> bool:
    """Is the message a first-person statement and NOT a third-party mention?

    Returns True only when the message uses first-person markers AND lacks
    third-party markers. Ambiguous messages (both or neither) return False
    so identity-shaped extractions get suppressed.
    """
    has_first_person = bool(_FIRST_PERSON_RE.search(message))
    has_third_party = bool(_THIRD_PARTY_RE.search(message))
    return has_first_person and not has_third_party


class _Extraction(BaseModel):
    key: str = Field(description="FactKey name (profession, home_city, etc.).")
    value: str = Field(description="Extracted value, trimmed.")
    confidence: Literal["low", "medium", "high"] = Field(default="low")
    is_correction: bool = Field(default=False)


class _ExtractionBatch(BaseModel):
    extracted: list[_Extraction] = Field(default_factory=list)


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text()
    except Exception:
        return "Extract canonical user facts. JSON: {extracted: [{key,value,confidence,is_correction}]}"


async def run(ctx: Mapping[str, Any]) -> None:
    user_id = ctx.get("user_id")
    inbound = (ctx.get("inbound") or "").strip()
    current_facts = ctx.get("user_facts") or {}
    if not user_id or not inbound:
        return

    # 1. Offline language signal — always runs.
    lang = detect_language(inbound)
    if lang is not None:
        try:
            await update_user_fact(
                user_id=user_id,
                key=FactKey.PRIMARY_LANGUAGE.value,
                value=lang,
                source=Source.OBSERVED_BEHAVIOR,
                confidence=Confidence.MEDIUM,
            )
        except Exception:
            logger.exception("extract_user_facts: language update failed")

    # 2. Haiku structured extraction.
    prompt = _load_prompt().format(
        message=inbound,
        current_facts=json.dumps(
            {k: (v.get("value") if isinstance(v, dict) else v) for k, v in current_facts.items()}
        ),
    )
    batch = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=prompt,
        user_message="Extract.",
        schema=_ExtractionBatch,
        max_tokens=300,
    )
    if batch is None:
        return

    valid = [e for e in batch.extracted if is_valid_fact_key(e.key)][:_MAX_EXTRACTIONS]
    message_is_first_person = _message_is_first_person_about_self(inbound)
    for item in valid:
        value = item.value.strip()
        if not value or item.confidence == "low":
            continue
        try:
            confidence = Confidence(item.confidence)
        except ValueError:
            continue
        # Identity-shaped fields (name, profession, city, age, life_stage,
        # household) only accept extractions from messages that are
        # unambiguously first-person about the user. This is the subject-
        # safety guard for the "Aayam Bansal" class of leak where Haiku
        # extracts a third party's name/profession onto the user.
        if item.key in _IDENTITY_KEYS and not message_is_first_person:
            logger.info(
                "extract_user_facts: suppressed third-party identity extraction "
                "user=%s key=%s value=%r (inbound not first-person)",
                user_id[:8],
                item.key,
                value[:40],
            )
            continue
        source = (
            Source.USER_CORRECTION if item.is_correction else Source.CONVERSATION_EXTRACTED
        )
        try:
            await update_user_fact(
                user_id=user_id,
                key=item.key,
                value=value,
                source=source,
                confidence=confidence,
            )
        except Exception:
            logger.exception("extract_user_facts: update failed for %s", item.key)
