"""Two-prompt synthesis + judge.

This is the node the user wanted — 'compare with another prompt'. Runs two
synthesis calls in parallel over the same reranked source pool using two
system prompts:

- ``_STRICT_SYSTEM``  — every claim must be source-backed, no weak signals.
- ``_BROAD_SYSTEM``   — weak signals allowed if marked.

Then a small judge call picks ``strict``, ``broad``, or ``merged`` and
records confidence plus any dissent worth preserving. All three calls are
Haiku to keep per-turn cost in line with Donna's $0.01/turn target.

Every call degrades gracefully: if Haiku is unavailable the function
returns the best available partial (one synthesis if only one succeeded,
empty if both failed). Never raises.
"""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured
from backend.web.types import WebAnswer, WebHit

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_ANSWER_CHARS = 900
_MAX_SOURCE_SNIPPET = 600


_STRICT_SYSTEM = """You answer research questions strictly from the supplied sources.

Rules:
- Every claim must be supported by at least one source.
- If sources disagree, name the disagreement. Do not resolve it.
- If sources don't cover the question, say so. Do not guess.
- Prose, 2-5 sentences, no bullet points.
- At most one claim per sentence.
- Never fabricate URLs or authors.

Return the answer body only. The pipeline attaches citations separately."""


_BROAD_SYSTEM = """You answer research questions using the supplied sources as primary
evidence, but you may include weak signals (a single source, a cautious
inference) when it makes the answer more useful.

Rules:
- Mark weak signals explicitly ("one source suggests", "unclear but").
- Prefer breadth over minimalism — include the texture of the question.
- Prose, 3-6 sentences, no bullet points.
- Never fabricate URLs or authors.

Return the answer body only. The pipeline attaches citations separately."""


_JUDGE_SYSTEM = """You are a research judge.

Given a question, two candidate answers (strict and broad), and the source
pool, produce:

1. choice: 'strict' if strict is clearly better supported; 'broad' if broad
   adds useful texture without overreach; 'merged' if the best answer is a
   short blend of both.
2. answer: final answer body. 2-5 sentences, no bullets, no inline
   citations — the pipeline attaches them.
3. confidence: 0..1, how firmly sources support the final answer.
4. dissent: if the unchosen answer raised a real point that should not be
   lost, one sentence. Else null.

Never fabricate. Low confidence is acceptable when sources are thin."""


class _SynthOut(BaseModel):
    answer: str = Field(description="Answer body, prose only, no citations.")


class _JudgeOut(BaseModel):
    choice: str = Field(description="'strict' | 'broad' | 'merged'")
    answer: str = Field(description="Final answer body the pipeline returns.")
    confidence: float = Field(description="0..1 support confidence.")
    dissent: str | None = Field(default=None)


def _format_sources(hits: list[WebHit], *, limit: int) -> str:
    lines: list[str] = ["Sources:"]
    for i, h in enumerate(hits[:limit], start=1):
        snippet = (h.snippet or "").replace("\n", " ").strip()[:_MAX_SOURCE_SNIPPET]
        tail = f" ({h.published_date})" if h.published_date else ""
        lines.append(f"[{i}] {h.title}{tail}\n    {h.url}\n    {snippet}")
    return "\n".join(lines)


async def _synthesize_one(system: str, question: str, sources_block: str) -> str:
    user = f"Question: {question}\n\n{sources_block}\n\nWrite the answer now."
    try:
        result = await call_structured(
            model=_MODEL,
            system_prompt=system,
            user_message=user,
            schema=_SynthOut,
            max_tokens=400,
            cache=True,
        )
    except Exception:
        logger.exception("synthesis call raised")
        return ""
    if result is None:
        return ""
    return result.answer.strip()[:_MAX_ANSWER_CHARS]


async def synthesize_with_compare(
    question: str,
    hits: list[WebHit],
    *,
    sources_limit: int = 8,
) -> WebAnswer:
    if not hits or not (question or "").strip():
        return WebAnswer(answer="", confidence=0.0, sources=list(hits[:sources_limit]))

    sources_block = _format_sources(hits, limit=sources_limit)

    strict, broad = await asyncio.gather(
        _synthesize_one(_STRICT_SYSTEM, question, sources_block),
        _synthesize_one(_BROAD_SYSTEM, question, sources_block),
        return_exceptions=True,
    )
    strict_text = strict if isinstance(strict, str) else ""
    broad_text = broad if isinstance(broad, str) else ""

    if not strict_text and not broad_text:
        return WebAnswer(
            answer="",
            confidence=0.0,
            sources=list(hits[:sources_limit]),
            metadata={"variant": "both_failed"},
        )
    if not strict_text:
        return WebAnswer(
            answer=broad_text,
            confidence=0.5,
            sources=list(hits[:sources_limit]),
            metadata={"variant": "broad_only"},
        )
    if not broad_text:
        return WebAnswer(
            answer=strict_text,
            confidence=0.6,
            sources=list(hits[:sources_limit]),
            metadata={"variant": "strict_only"},
        )

    judge_user = (
        f"Question: {question}\n\n"
        f"Strict answer:\n{strict_text}\n\n"
        f"Broad answer:\n{broad_text}\n\n"
        f"{sources_block}\n\n"
        "Produce the judgement now."
    )
    try:
        judged = await call_structured(
            model=_MODEL,
            system_prompt=_JUDGE_SYSTEM,
            user_message=judge_user,
            schema=_JudgeOut,
            max_tokens=500,
            cache=True,
        )
    except Exception:
        logger.exception("judge call raised")
        judged = None

    if judged is None:
        return WebAnswer(
            answer=strict_text,
            confidence=0.5,
            sources=list(hits[:sources_limit]),
            dissent=broad_text,
            metadata={"variant": "strict_fallback"},
        )

    final = (judged.answer or "").strip()[:_MAX_ANSWER_CHARS] or strict_text
    confidence = max(0.0, min(1.0, float(judged.confidence)))
    dissent = (judged.dissent or "").strip() or None
    variant = judged.choice if judged.choice in {"strict", "broad", "merged"} else "merged"
    return WebAnswer(
        answer=final,
        confidence=confidence,
        sources=list(hits[:sources_limit]),
        dissent=dissent,
        metadata={"variant": variant},
    )
