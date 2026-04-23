"""Author an AttentionSpec from a normalized intent + retrieved gold examples.

Uses Haiku via `backend.memory.retrieval.structured.call_structured`. Validates
the returned payload against AttentionSpec. On validation failure, retries once
with the error feedback appended to the user message.

Bare reminders short-circuit to a Ping spec without an LLM call.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from donna.attention.examples.gold_specs import GOLD_EXAMPLES, GoldExample
from donna.attention.normalize import NormalizedIntent, UserContext
from donna.attention.retrieve import Retrieved, retrieve_top_k
from donna.attention.schema import (
    AttentionSpec,
    Cadence,
    Extractor,
    Source,
    Subject,
    SurfacePolicy,
)
from donna.attention.vocabulary import (
    SOURCE_PARAMS_MODELS,
    CadenceType,
    CardType,
    SourceType,
    SubjectType,
    SurfaceLevel,
    vocabulary_summary,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "author.md"
_PROMPT_TEMPLATE: str | None = None


def _load_prompt() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")
    return _PROMPT_TEMPLATE


# -- LLM payload schema ------------------------------------------------------


class _AuthorPayload(BaseModel):
    """The LLM emits this; we unwrap to an AttentionSpec."""

    model_config = ConfigDict(extra="forbid")
    spec: AttentionSpec
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=800)


# Haiku 4.5 list pricing (USD per token). Cached input reads are 10x cheaper
# than fresh input; cache writes cost 25% more. Output is flat. Update if
# pricing changes — this is the one place that has to know the rates.
_USD_PER_INPUT_TOKEN = 1.00 / 1_000_000
_USD_PER_OUTPUT_TOKEN = 5.00 / 1_000_000
_USD_PER_CACHE_READ_TOKEN = 0.10 / 1_000_000
_USD_PER_CACHE_WRITE_TOKEN = 1.25 / 1_000_000


@dataclass(frozen=True)
class Usage:
    """Per-call token counts and derived USD cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    retries: int = 0

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * _USD_PER_INPUT_TOKEN
            + self.output_tokens * _USD_PER_OUTPUT_TOKEN
            + self.cache_read_tokens * _USD_PER_CACHE_READ_TOKEN
            + self.cache_creation_tokens * _USD_PER_CACHE_WRITE_TOKEN
        )


@dataclass(frozen=True)
class AuthorResult:
    spec: AttentionSpec
    confidence: float
    reasoning: str
    retrieved_ids: tuple[str, ...]
    via: str  # "llm" | "ping_shortcircuit" | "fallback"
    usage: Usage | None = None


# -- Ping short-circuit ------------------------------------------------------


_BARE_REMINDER_PATTERNS = [
    r"remind me (to|that|about)\b",
    r"^ping me\b",
    r"^set (a )?reminder\b",
    r"don'?t let me forget\b",
]

_DOW_MAP = {
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2, "tues": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thurs": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
    "sunday": 0, "sun": 0,
}

_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _looks_like_bare_reminder(raw: str) -> bool:
    low = raw.lower()
    return any(re.search(p, low) for p in _BARE_REMINDER_PATTERNS)


def _to_24h(hour: int, minute: int, meridiem: str) -> tuple[int, int]:
    m = (meridiem or "").lower()
    if m == "pm" and hour < 12:
        hour += 12
    if m == "am" and hour == 12:
        hour = 0
    return hour % 24, minute


def _parse_time_hhmm(raw: str) -> tuple[int, int] | None:
    """Find the first HH(:MM)?(am|pm)? near 'at ...' preferentially."""
    low = raw.lower()
    m = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", low
    )
    if not m:
        m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3) or ""
    return _to_24h(hour, minute, meridiem)


def _parse_reminder(raw: str, user_tz: str) -> Cadence:
    """Parse a bare reminder into a Cadence honoring user_tz.

    Priority: interval > weekly > monthly-day > daily > in-N > at-time > fallback.
    """
    tz = ZoneInfo(user_tz)
    now = datetime.now(tz=tz)
    low = raw.lower()

    # every N minutes/hours
    m = re.search(r"\bevery\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b", low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        seconds = n * 60 if unit.startswith("min") else n * 3600
        return Cadence(type=CadenceType.SCHEDULED, params={"interval_seconds": seconds})

    # every N days -> scheduled cron at 9am every N days (approximate via interval)
    m = re.search(r"\bevery\s+(\d+)\s*days?\b", low)
    if m:
        n = int(m.group(1))
        return Cadence(
            type=CadenceType.SCHEDULED,
            params={"interval_seconds": n * 86400},
        )

    # every <dow> [at HH(:MM) (am|pm)?]
    dow_re = r"\bevery\s+(" + "|".join(_DOW_MAP.keys()) + r")\b"
    m = re.search(dow_re, low)
    if m:
        dow = _DOW_MAP[m.group(1)]
        t = _parse_time_hhmm(raw) or (9, 0)
        return Cadence(
            type=CadenceType.SCHEDULED,
            params={"cron": f"{t[1]} {t[0]} * * {dow}"},
        )

    # on the Nth (of every month | each month | every month | of the month) with optional time
    m = re.search(
        r"\bon the (\d{1,2})(?:st|nd|rd|th)?\b.*?\b(of every month|of each month|every month|each month|of the month)\b",
        low,
    )
    if m:
        day = int(m.group(1))
        t = _parse_time_hhmm(raw) or (9, 0)
        return Cadence(
            type=CadenceType.SCHEDULED,
            params={"cron": f"{t[1]} {t[0]} {day} * *"},
        )
    # "on the 5th every month" (order variant)
    m = re.search(r"\bon the (\d{1,2})(?:st|nd|rd|th)?\s+every month\b", low)
    if m:
        day = int(m.group(1))
        t = _parse_time_hhmm(raw) or (9, 0)
        return Cadence(
            type=CadenceType.SCHEDULED,
            params={"cron": f"{t[1]} {t[0]} {day} * *"},
        )

    # every day at HH(:MM)
    if re.search(r"\bevery day\b|\bdaily\b", low):
        t = _parse_time_hhmm(raw) or (9, 0)
        return Cadence(
            type=CadenceType.SCHEDULED,
            params={"cron": f"{t[1]} {t[0]} * * *"},
        )

    # "in N minutes|hours|days" or "N minutes from now"
    m = re.search(r"\bin\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs|day|days)\b", low)
    if not m:
        m = re.search(r"\b(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs|day|days)\s+from now\b", low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("min"):
            delta = timedelta(minutes=n)
        elif unit.startswith("h"):
            delta = timedelta(hours=n)
        else:
            delta = timedelta(days=n)
        target = now + delta
        return Cadence(type=CadenceType.ONE_SHOT, params={"trigger_at": target.isoformat()})

    # date like "june 5" or "on june 5"
    month_re = r"\b(?:on\s+)?(" + "|".join(_MONTH_MAP.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b"
    m = re.search(month_re, low)
    if m:
        month = _MONTH_MAP[m.group(1)]
        day = int(m.group(2))
        t = _parse_time_hhmm(raw) or (9, 0)
        year = now.year
        candidate = datetime(year, month, day, t[0], t[1], tzinfo=tz)
        if candidate <= now:
            candidate = datetime(year + 1, month, day, t[0], t[1], tzinfo=tz)
        return Cadence(
            type=CadenceType.ONE_SHOT, params={"trigger_at": candidate.isoformat()}
        )

    # at HH(:MM) (am|pm)? with optional tomorrow/today
    t = _parse_time_hhmm(raw)
    if t is not None:
        target = now.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
        if "tomorrow" in low:
            target = target + timedelta(days=1)
        elif target <= now:
            target = target + timedelta(days=1)
        return Cadence(type=CadenceType.ONE_SHOT, params={"trigger_at": target.isoformat()})

    # fallback: now + 1h in user_tz
    target = now + timedelta(hours=1)
    return Cadence(type=CadenceType.ONE_SHOT, params={"trigger_at": target.isoformat()})


def _ping_spec(
    raw: str, normalized: NormalizedIntent, user_tz: str = "Asia/Singapore"
) -> AttentionSpec:
    subject_name = normalized.signals.subject_name or raw.strip()[:60] or "reminder"
    question = raw.strip().rstrip(".?!")[:200] or "reminder"
    cadence = _parse_reminder(raw, user_tz)
    desc_prefix = "Scheduled reminder" if cadence.type is CadenceType.SCHEDULED else "One-shot reminder"
    return AttentionSpec(
        title=subject_name[:70] or "reminder",
        description=f"{desc_prefix}: {question}",
        card=CardType.PING,
        subject=Subject(name=subject_name[:140], type=SubjectType.EVENT),
        domain_tags=[normalized.signals.domain_tag_or_reminder()]
        if hasattr(normalized.signals, "domain_tag_or_reminder")
        else _reminder_domain_tags(normalized),
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": question, "expected_shape": "confirmation"},
            )
        ],
        extractor=Extractor(prompt="Deliver the reminder message at trigger time."),
        cadence=cadence,
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
    )


def _reminder_domain_tags(normalized: NormalizedIntent):
    from donna.attention.vocabulary import DomainTag

    domain = normalized.signals.domain
    try:
        return [DomainTag(domain), DomainTag.REMINDER]
    except ValueError:
        return [DomainTag.REMINDER]


# -- Prompt helpers ----------------------------------------------------------


def _gold_examples_block(examples: list[GoldExample]) -> str:
    """Render a compact JSON block of up-to-k examples for the prompt."""
    out = []
    for ex in examples:
        out.append(
            {
                "id": ex.example_id,
                "intents": list(ex.intent_examples)[:3],
                "spec": ex.spec.model_dump(mode="json"),
                "rationale": ex.rationale,
            }
        )
    return json.dumps(out, indent=2)


def _source_params_block() -> str:
    out = {
        st.value: list(model.model_fields.keys())
        for st, model in SOURCE_PARAMS_MODELS.items()
    }
    return json.dumps(out, indent=2)


_PROMPT_SPLIT_MARKER = "PER-CALL CONTEXT:"


def _build_prompt(
    normalized: NormalizedIntent,
    user_context: UserContext,
    examples: list[GoldExample],
) -> tuple[str, str]:
    """Return (stable_prefix, variable_suffix).

    Prefix (cached): rubric + closed vocabulary + full gold library +
    output rules. Fat enough (>8k tokens) to clear Haiku 4.5's cache
    threshold, and fully stable across calls.

    Suffix (uncached): per-user context, normalized intent, and the
    retrieval-emphasized example ids.
    """
    emphasized_ids = ", ".join(ex.example_id for ex in examples) or "(none)"
    filled = _load_prompt().format(
        vocabulary=json.dumps(vocabulary_summary(), indent=2),
        source_params=_source_params_block(),
        gold_library=_gold_examples_block(list(GOLD_EXAMPLES)),
        user_context=json.dumps(
            {
                "user_id": user_context.user_id,
                "living_profile": user_context.living_profile or "(none)",
                "active_state": user_context.active_state or "(none)",
            },
            indent=2,
        ),
        normalized_intent=json.dumps(
            {
                "raw_text": normalized.raw_text,
                "normalized_text": normalized.normalized_text,
                "signals": normalized.signals.model_dump(),
            },
            indent=2,
        ),
        emphasized_ids=emphasized_ids,
    )
    if _PROMPT_SPLIT_MARKER in filled:
        prefix, suffix = filled.split(_PROMPT_SPLIT_MARKER, 1)
        return prefix.rstrip(), _PROMPT_SPLIT_MARKER + suffix
    return filled, ""


# -- Public API --------------------------------------------------------------


async def author_spec(
    normalized: NormalizedIntent,
    user_context: UserContext,
    retrieved: list[Retrieved] | None = None,
    *,
    k: int = 3,
    model: str = "claude-haiku-4-5-20251001",
    timeout: float = 12.0,
) -> AuthorResult:
    """Author an AttentionSpec; short-circuit bare reminders to Ping card."""
    raw = normalized.raw_text

    if _looks_like_bare_reminder(raw):
        try:
            spec = _ping_spec(raw, normalized, user_context.user_tz)
            return AuthorResult(
                spec=spec,
                confidence=0.9,
                reasoning="Bare reminder → Ping short-circuit (no LLM call).",
                retrieved_ids=(),
                via="ping_shortcircuit",
            )
        except ValidationError:
            logger.warning("ping short-circuit failed validation; falling through")

    if retrieved is None:
        retrieved = retrieve_top_k(raw, k=k)
    retrieved_ids = tuple(r.example.example_id for r in retrieved)

    prefix, suffix = _build_prompt(
        normalized, user_context, [r.example for r in retrieved]
    )

    call = await _call_with_validation_retry(
        prompt=prefix,
        suffix=suffix,
        user_message=raw,
        model=model,
        timeout=timeout,
    )

    if call is None or call[0] is None:
        logger.info("author: LLM unavailable or retries exhausted — nearest-gold fallback")
        return _fallback_from_retrieval(normalized, retrieved)

    payload, usage = call
    return AuthorResult(
        spec=payload.spec,
        confidence=payload.confidence,
        reasoning=payload.reasoning,
        retrieved_ids=retrieved_ids,
        via="retry" if usage.retries > 0 else "llm",
        usage=usage,
    )


# -- LLM call with one retry on validation error -----------------------------


def _build_system_blocks(prefix: str, suffix: str) -> list[dict]:
    """Two-block system: cached stable prefix + uncached per-call suffix."""
    blocks: list[dict] = [
        {
            "type": "text",
            "text": prefix,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if suffix:
        blocks.append({"type": "text", "text": suffix})
    return blocks


async def _call_with_validation_retry(
    *,
    prompt: str,
    user_message: str,
    model: str,
    timeout: float,
    suffix: str = "",
) -> tuple[_AuthorPayload | None, Usage] | None:
    """Call Haiku, validate, retry once with error feedback on ValidationError.

    Returns `(payload, usage)` on success. ``usage`` aggregates token counts
    across every attempt (so a retry's tokens are billed to the caller).
    Returns None if the call couldn't be made at all (no key, no client).
    """
    try:
        from backend.config import get_settings
    except ImportError:
        return None
    settings = get_settings()
    if not getattr(settings, "anthropic_api_key", None):
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return None
    import asyncio

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tool_name = "emit_attention_spec"
    tool = {
        "name": tool_name,
        "description": "Emit the AttentionSpec wrapped in confidence + reasoning.",
        "input_schema": _AuthorPayload.model_json_schema(),
    }

    current_message = user_message
    last_error: str | None = None
    agg = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "retries": 0,
    }

    def _accumulate(resp) -> None:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        agg["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        agg["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        agg["cache_read_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        agg["cache_creation_tokens"] += (
            getattr(u, "cache_creation_input_tokens", 0) or 0
        )

    for attempt in range(2):
        if last_error and attempt == 1:
            agg["retries"] += 1
            current_message = (
                f"{user_message}\n\n"
                f"Previous attempt failed pydantic validation. Fix these errors:\n"
                f"{last_error}\n"
                "Return a new valid AttentionSpec payload."
            )
        try:
            resp = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=1500,
                    system=_build_system_blocks(prompt, suffix),
                    messages=[{"role": "user", "content": current_message}],
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("author call timeout (attempt %d)", attempt + 1)
            return (None, Usage(**agg))
        except Exception:
            logger.exception("author call failed (attempt %d)", attempt + 1)
            return (None, Usage(**agg))

        _accumulate(resp)
        block = next(
            (b for b in resp.content if getattr(b, "type", "") == "tool_use" and b.name == tool_name),
            None,
        )
        if block is None:
            return (None, Usage(**agg))
        try:
            return (_AuthorPayload.model_validate(block.input), Usage(**agg))
        except ValidationError as e:
            last_error = str(e)
            logger.info("author: validation failed attempt %d, retrying with feedback", attempt + 1)
            continue
    logger.warning("author: both attempts failed validation")
    return (None, Usage(**agg))


def _fallback_from_retrieval(
    normalized: NormalizedIntent, retrieved: list[Retrieved]
) -> AuthorResult:
    """When the LLM is unavailable, return the top gold example's spec."""
    if not retrieved:
        raise RuntimeError("no gold examples available for fallback")
    top = retrieved[0]
    return AuthorResult(
        spec=top.example.spec,
        confidence=0.4,
        reasoning=f"Fallback: nearest gold ({top.example.example_id}).",
        retrieved_ids=tuple(r.example.example_id for r in retrieved),
        via="fallback",
    )
