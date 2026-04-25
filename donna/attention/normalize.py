"""Normalize a raw user intent into a structured NormalizedIntent.

Uses Haiku via :mod:`backend.memory.retrieval.structured.call_structured`.
Falls back to a rule-based heuristic if the LLM call returns None
(missing API key, timeout, parse failure).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "normalize.md"
_PROMPT_TEMPLATE: str | None = None


def _load_prompt() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")
    return _PROMPT_TEMPLATE


# -- Data classes -----------------------------------------------------------


@dataclass(frozen=True)
class UserContext:
    """Minimal user context slice fed to normalization + authoring."""

    user_id: str
    living_profile: str = ""
    active_state: str = ""
    user_tz: str = "Asia/Singapore"


async def load_user_timezone(user_id: str) -> str | None:
    """Best-effort DB lookup for the user's operational timezone.

    Returns None if the DB is unreachable (CLI/test environments) or the user
    has no timezone set. Callers should fall back to the UserContext default.
    """
    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session
    except Exception:
        return None

    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            return str(user.timezone).strip() if user and user.timezone else None
    except Exception:
        return None


class NormalizedSignals(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_type: Literal["entity", "domain", "event", "thread"] = "domain"
    pattern: Literal["watch", "brief", "prep", "track", "loop"] = "watch"
    duration: Literal["ongoing", "one_shot", "recurring"] = "ongoing"
    surface_intent: Literal["interrupt", "silent", "digest"] = "digest"
    domain: str = "work"
    urgency: Literal["low", "medium", "high"] = "medium"
    subject_name: str = ""


class NormalizedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_text: str
    normalized_text: str
    signals: NormalizedSignals = Field(default_factory=NormalizedSignals)
    embedding: list[float] | None = None


class _NormalizePayload(BaseModel):
    """Schema the LLM is instructed to emit via tool-use."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    normalized_text: str
    signals: NormalizedSignals


# -- Heuristic fallback -----------------------------------------------------


_PATTERN_HINTS = {
    "loop": ["close the loop", "follow up", "follow-up", "pending reply", "still waiting"],
    "prep": ["prep ", "remind me", "before ", "ahead of", "get ready"],
    "brief": ["summarize", "digest", "roundup", "recap", "weekly", "review"],
    "track": ["track ", "log ", "count ", "how many", "expense", "spent", "over the month", "quality over"],
    "watch": ["watch", "keep an eye", "monitor", "follow the", "news"],
}
_DOMAIN_HINTS = {
    "fundraising": ["raise", "fund", "vc", "investor", "series a", "seed"],
    "shipment": ["shipment", "package", "delivery", "tracking number"],
    "flight": ["flight", "airline", "boarding"],
    "travel": ["trip", "hotel", "itinerary"],
    "finance": ["expense", "spend", "cost", "bill", "subscription"],
    "learning": ["learn", "paper", "arxiv", "tutorial", "course"],
    "health": ["workout", "sleep", "steps", "calories", "meditate"],
    "social": ["friend", "birthday", "message", "text"],
    "logistics": ["deliver", "route", "commute", "weather"],
    "meeting": ["meeting", "call", "sync", "1:1"],
    "research": ["research", "study", "paper"],
    "competitive_intel": ["competitor", "rival", "poke"],
}


def _heuristic_normalize(raw: str) -> NormalizedIntent:
    lowered = raw.lower()

    pattern = "watch"
    for p, hints in _PATTERN_HINTS.items():
        if any(h in lowered for h in hints):
            pattern = p
            break

    domain = "work"
    for d, hints in _DOMAIN_HINTS.items():
        if any(h in lowered for h in hints):
            domain = d
            break

    duration = "ongoing"
    if pattern == "prep" or re.search(r"\b(remind me|before|ahead of)\b", lowered):
        duration = "one_shot"
    elif re.search(r"\b(weekly|daily|every \w+|each \w+)\b", lowered):
        duration = "recurring"

    surface = "digest"
    if re.search(r"\b(urgent|immediately|interrupt|ping me|right away)\b", lowered):
        surface = "interrupt"
    elif pattern in ("brief", "track"):
        surface = "silent"

    subject_type = "entity"
    quoted = re.search(r'"([^"]+)"', raw) or re.search(r"\b([A-Z][a-zA-Z]+)\b", raw)
    subject_name = quoted.group(1) if quoted else ""
    if not subject_name:
        subject_type = "domain"

    urgency = "high" if surface == "interrupt" else "medium" if pattern != "track" else "low"

    signals = NormalizedSignals(
        subject_type=subject_type,
        pattern=pattern,
        duration=duration,
        surface_intent=surface,
        domain=domain,
        urgency=urgency,
        subject_name=subject_name,
    )
    normalized_text = (
        f"{duration} {'monitoring' if pattern=='watch' else 'tracking' if pattern=='track' else 'synthesis' if pattern=='brief' else 'preparation' if pattern=='prep' else 'loop'} "
        f"of {subject_type}"
        + (f" ({subject_name})" if subject_name else "")
        + f", {pattern} pattern, {surface} surface intent, {domain} domain"
    )
    return NormalizedIntent(raw_text=raw, normalized_text=normalized_text, signals=signals)


# -- Public API -------------------------------------------------------------


async def normalize_intent(
    intent: str,
    user_context: UserContext,
    *,
    model: str = "claude-haiku-4-5-20251001",
    timeout: float = 8.0,
) -> NormalizedIntent:
    """Normalize a raw intent. Falls back to heuristic on LLM failure."""
    raw = intent.strip()
    if not raw:
        raise ValueError("intent must be non-empty")

    try:
        from backend.memory.retrieval.structured import call_structured
    except ImportError:
        logger.info("call_structured unavailable — heuristic fallback")
        return _heuristic_normalize(raw)

    prompt = _load_prompt().format(
        user_profile=user_context.living_profile or "(none)",
        active_state=user_context.active_state or "(none)",
        raw_intent=raw,
    )

    payload = await call_structured(
        model=model,
        system_prompt=prompt,
        user_message=raw,
        schema=_NormalizePayload,
        max_tokens=400,
        timeout=timeout,
    )
    if payload is None:
        logger.info("normalize: LLM unavailable — heuristic fallback")
        return _heuristic_normalize(raw)

    return NormalizedIntent(
        raw_text=raw,
        normalized_text=payload.normalized_text,
        signals=payload.signals,
    )
