"""Query expansion for the web research pipeline.

Haiku reads the research question and produces:

- ``rewritten_query``: terse, self-contained rewrite.
- ``neural_queries``: 1-3 descriptive, sentence-shaped queries tuned for
  Exa's neural search (it treats queries like prose).
- ``keyword_queries``: 1-2 terse queries for Exa keyword mode — names,
  exact phrases, technical terms.
- ``hypothetical``: optional HyDE snippet, one sentence shaped like the
  answer body. Exa neural loves these.

Falls back to a naive single-query expansion when Haiku is unavailable
(missing key, timeout, parse failure) — pipeline never stalls on expansion.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured
from backend.web.types import WebExpansion

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"


class _ExpansionOut(BaseModel):
    rewritten_query: str = Field(description="Terse rewrite, pronouns + time refs resolved.")
    neural_queries: list[str] = Field(default_factory=list)
    keyword_queries: list[str] = Field(default_factory=list)
    hypothetical: str | None = Field(default=None)


_SYSTEM_PROMPT = """You plan web retrieval for a deep-research pipeline.

Given a research question, produce:

1. rewritten_query: terse, self-contained (pronouns + time refs resolved).
2. neural_queries: 1-3 descriptive sentence-shaped queries. Exa's neural
   search treats queries like prose — write them as partial sentences such
   as 'articles comparing the design tradeoffs of X and Y', not keywords.
3. keyword_queries: 1-2 terse queries for Exa keyword mode. Use them for
   named entities, exact phrases, technical terms.
4. hypothetical: one sentence written as if it is the answer body. HyDE-
   style additional neural query. Omit when the question is too open-ended
   to guess a plausible answer shape.

Do NOT invent facts. Keep every string under 200 chars."""


def _naive_fallback(question: str) -> WebExpansion:
    return WebExpansion(
        rewritten_query=question,
        neural_queries=[question],
        keyword_queries=[],
        hypothetical=None,
    )


async def expand_research_query(
    question: str,
    *,
    profile_blurb: str = "",
) -> WebExpansion:
    q = (question or "").strip()
    if not q:
        return WebExpansion(
            rewritten_query="",
            neural_queries=[],
            keyword_queries=[],
            hypothetical=None,
        )

    user_block = f"Research question: {q!r}"
    if profile_blurb:
        user_block += f"\n\nUser profile:\n{profile_blurb}"
    user_block += "\n\nProduce the retrieval plan now."

    try:
        result = await call_structured(
            model=_MODEL,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_block,
            schema=_ExpansionOut,
            max_tokens=400,
            cache=True,
        )
    except Exception:
        logger.exception("expand_research_query: call_structured raised")
        return _naive_fallback(q)

    if result is None:
        return _naive_fallback(q)

    neural = [s.strip() for s in (result.neural_queries or []) if s and s.strip()]
    keyword = [s.strip() for s in (result.keyword_queries or []) if s and s.strip()]
    if not neural:
        neural = [q]

    return WebExpansion(
        rewritten_query=(result.rewritten_query or q).strip(),
        neural_queries=neural[:3],
        keyword_queries=keyword[:2],
        hypothetical=(result.hypothetical or None) and result.hypothetical.strip() or None,
    )
