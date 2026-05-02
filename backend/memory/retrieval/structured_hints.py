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
    wants_calendar: bool = False


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
    # Conversational phrasings that imply "what did i commit to"
    "what am i tracking",
    "what i'm tracking",
    "what i am tracking",
    "what did i say i'd do",
    "what did i say id do",
    "what did i say i would do",
    "what's on my plate",
    "whats on my plate",
    "what is on my plate",
    "what's pulling on me",
    "whats pulling on me",
    "what is pulling on me",
    "to do",
    "todo",
    "todos",
    "to-do",
    "to-dos",
)


_HABIT_VERBS_PAST = (
    "drank",
    "ate",
    "slept",
    "weighed",
    "ran",
    "walked",
    "meditated",
    "exercised",
    "worked out",
    "logged",
    "tracked",
    "trained",
)

_HABIT_VERBS_PRESENT = (
    "drink",
    "eat",
    "sleep",
    "weigh",
    "run",
    "walk",
    "meditate",
    "exercise",
    "workout",
    "log",
    "track",
    "train",
)


_CALENDAR_PHRASES = (
    "calendar",
    "schedule",
    "scheduled",
    "meeting",
    "meetings",
    "appointment",
    "appointments",
    "on my plate",
    "what's on",
    "whats on",
    "what is on",
    "agenda",
    "today's plan",
    "todays plan",
    "this week's plan",
    "lunch with",
    "dinner with",
    "call with",
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
    has_habit_shape = _detect_habit_shape(original_text) or _detect_habit_shape(text)
    wants_observations = bool(
        observation_type
        or any(phrase in text for phrase in _QUANT_WORDS)
        or re.search(r"\b\d+(\.\d+)?\b", text)
        or has_habit_shape
    )
    wants_open_loops = any(phrase in text for phrase in _OPEN_LOOP_PHRASES)
    wants_situation_brief = any(phrase in text for phrase in _SITUATION_PHRASES)
    wants_calendar = any(phrase in text for phrase in _CALENDAR_PHRASES) or bool(
        period and re.search(r"\b(today|tomorrow|this\s+week|next\s+week)\b", text)
    )
    return StructuredHints(
        observation_type=observation_type,
        period=period,
        wants_observations=wants_observations,
        wants_open_loops=wants_open_loops,
        wants_situation_brief=wants_situation_brief,
        wants_calendar=wants_calendar,
    )


def _detect_habit_shape(text: str) -> bool:
    """Catch ``did i <verb> today/this week`` and bare habit verbs.

    The observation_type detector already covers many habit nouns ('water',
    'sleep', 'meal'), but it misses temporal habit questions like
    "did i drink water today" when the verb form is the cue rather than the
    noun. Returning True here flips ``wants_observations`` so the
    observations lane is queried with the right time bounds.
    """
    if not text:
        return False
    # "did i <verb> ..." or "have i <verb> ..."
    if re.search(r"\b(did|have|did\s+i|have\s+i)\b", text):
        for verb in _HABIT_VERBS_PAST + _HABIT_VERBS_PRESENT:
            if re.search(rf"\b{re.escape(verb)}\b", text):
                return True
    # bare past-tense habit verbs imply a logging question
    for verb in _HABIT_VERBS_PAST:
        if re.search(rf"\b{re.escape(verb)}\b", text):
            return True
    return False


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
