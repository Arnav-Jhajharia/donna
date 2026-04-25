"""Cheap deterministic hints for structured retrieval lanes."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class StructuredHints:
    observation_type: str | None = None
    period: str | None = None
    wants_observations: bool = False
    wants_open_loops: bool = False
    wants_situation_brief: bool = False


_OBSERVATION_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("expense", ("spend", "spent", "expense", "expenses", "paid", "cost", "bucks", "dollars", "usd", "sgd", "inr", "coffee")),
    ("meal", ("eat", "ate", "meal", "food", "breakfast", "lunch", "dinner", "snack", "calories")),
    ("sleep", ("sleep", "slept", "nap", "bed", "woke")),
    ("mood", ("mood", "felt", "feeling", "anxious", "nervous", "sad", "happy", "score")),
    ("exercise", ("exercise", "workout", "run", "gym", "steps", "walk")),
    ("habit", ("habit", "streak", "meditate", "meditation", "drink", "drank", "water")),
)

_QUANT_WORDS = (
    "how much",
    "how many",
    "how often",
    "average",
    "avg",
    "total",
    "sum",
    "count",
    "track",
    "tracked",
)

_OPEN_LOOP_PHRASES = (
    "what am i forgetting",
    "open loop",
    "open loops",
    "loose thread",
    "loose threads",
    "follow up",
    "follow-up",
    "pending",
    "unresolved",
    "owed",
    "need to do",
    "still need",
)

_SITUATION_PHRASES = (
    "what's going on",
    "what is going on",
    "where am i at",
    "what's live",
    "what is live",
    "current status",
    "my week",
    "about my week",
    "how fresh",
    "what do you know about my week",
)

_STOPWORDS = {
    "a", "am", "an", "and", "are", "at", "be", "did", "do", "for", "from",
    "have", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or",
    "that", "the", "this", "to", "was", "what", "when", "where", "with",
}


def detect_structured_hints(message: str, queries: list[str] | None = None) -> StructuredHints:
    """Return deterministic retrieval hints without an LLM call."""
    original_text = (message or "").lower()
    text = " ".join([message or "", *(queries or [])]).lower()
    observation_type = _detect_observation_type(text)
    # Expansion text is allowed to add recall facets, but it must not override
    # an explicit temporal boundary in the user's actual question.
    period = _detect_period(original_text) or _detect_period(text)
    wants_observations = bool(
        observation_type
        or any(phrase in text for phrase in _QUANT_WORDS)
        or re.search(r"\b\d+(\.\d+)?\b", text)
    )
    wants_open_loops = any(phrase in text for phrase in _OPEN_LOOP_PHRASES)
    wants_situation_brief = any(phrase in text for phrase in _SITUATION_PHRASES)
    return StructuredHints(
        observation_type=observation_type,
        period=period,
        wants_observations=wants_observations,
        wants_open_loops=wants_open_loops,
        wants_situation_brief=wants_situation_brief,
    )


def query_terms(text: str, *, limit: int = 8) -> list[str]:
    """Small token set for structured text-match fallback."""
    out: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_'-]{2,}", (text or "").lower()):
        cleaned = token.strip("_'-")
        if cleaned in _STOPWORDS or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _detect_observation_type(text: str) -> str | None:
    for obs_type, words in _OBSERVATION_TYPES:
        if any(re.search(rf"\b{re.escape(word)}\b", text) for word in words):
            return obs_type
    return None


def _detect_period(text: str) -> str | None:
    if re.search(r"\btoday\b", text):
        return "today"
    if re.search(r"\byesterday\b", text):
        return "yesterday"
    if re.search(r"\bthis\s+week\b|\bweekly\b", text):
        return "this_week"
    if re.search(r"\blast\s+week\b", text):
        return "last_week"
    return None
