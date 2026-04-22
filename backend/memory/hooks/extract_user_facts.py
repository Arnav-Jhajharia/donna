"""Haiku subagent that extracts canonical user facts and writes via
update_user_fact (spec §6).

Also runs a cheap offline language detector on every turn so
primary_language upgrades from the default seed.
"""
from __future__ import annotations

import json
import logging
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
    for item in valid:
        value = item.value.strip()
        if not value or item.confidence == "low":
            continue
        try:
            confidence = Confidence(item.confidence)
        except ValueError:
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
