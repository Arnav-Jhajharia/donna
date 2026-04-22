"""Query expansion — rewrite + facets + HyDE. Ported from backend-v2."""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

Intent = Literal[
    "recall", "explore", "reflective", "capture", "emotional",
    "question", "casual", "unknown",
]

_HYDE_INTENTS = {"recall", "explore", "reflective", "question"}


class ExpansionOut(BaseModel):
    rewritten_query: str = Field(description="Coref + time resolved query for embedding.")
    facets: list[str] = Field(default_factory=list, description="2-3 NL queries.")
    hypothetical: str | None = Field(default=None, description="Optional HyDE snippet.")


_SYSTEM_PROMPT = """You plan retrieval for a personal AI assistant named Donna.

Given a user message and a short profile blurb, you produce:

1. rewritten_query: pronouns + time refs resolved, terse (embedding input).
2. facets: 2-3 NL queries covering different angles. Stay specific.
3. hypothetical: for recall/explore/reflective/question intents only — write ONE
   hypothetical memory shaped like the answer. Leave null otherwise.

Do NOT invent facts. Keep every string under 200 chars."""


async def expand_query(
    *,
    message: str,
    profile_blurb: str = "",
    recent_thread: str = "",
    current_datetime: str = "",
    intent_hint: Intent = "unknown",
) -> ExpansionOut | None:
    user_block = _build_user_block(
        message=message,
        profile_blurb=profile_blurb,
        recent_thread=recent_thread,
        current_datetime=current_datetime,
        intent_hint=intent_hint,
    )
    result = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=_SYSTEM_PROMPT,
        user_message=user_block,
        schema=ExpansionOut,
        max_tokens=400,
        cache=True,
    )
    if result is None:
        return None
    if intent_hint not in _HYDE_INTENTS and intent_hint != "unknown":
        result = result.model_copy(update={"hypothetical": None})
    return result


def _build_user_block(
    *,
    message: str,
    profile_blurb: str,
    recent_thread: str,
    current_datetime: str,
    intent_hint: Intent,
) -> str:
    parts = [f"Message: {message!r}"]
    if intent_hint != "unknown":
        parts.append(f"Intent hint: {intent_hint}")
    if current_datetime:
        parts.append(f"Current time: {current_datetime}")
    if profile_blurb:
        parts.append(f"User profile:\n{profile_blurb}")
    if recent_thread:
        parts.append(f"Recent thread:\n{recent_thread}")
    parts.append("Produce the retrieval plan now.")
    return "\n\n".join(parts)
