"""Worth-telling judge — does this result actually earn an interrupt?

After the executor returns a ``ProactiveResult``, this module asks Haiku:
*given the user's current state, is this finding worth pinging the user
about?* The judge can:

- **send**: it earns the ping. Return a draft message in the user's voice
  (lowercase, terse, no em dashes).
- **silence**: not worth it. Return the reason for the trace.

The judge defaults to **silence** when the model is unavailable or the
output doesn't parse. Silence is always safe; sending isn't.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured
from backend.web.proactive.types import (
    ProactiveContext,
    ProactiveMove,
    ProactiveResult,
)

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_DRAFT_CHARS = 600
_MAX_REASON_CHARS = 240


JudgeDecision = Literal["send", "silence"]


_SYSTEM_PROMPT = """You decide whether a proactive search result is worth interrupting the user with.

You read:
- the user's Living Profile + Situation Brief + recent thread
- the proactive move Donna chose to run, with its hypothesis,
  user_signal, and payoff_if_hit
- the result the move returned

You output one of:

1. SEND - the finding is sharp, fresh, anchored to a real user signal,
   AND surprising (not something the user could have inferred from their
   own profile alone). Provide a draft message ready to ship, in Donna's
   voice:
   - lowercase
   - terse, high-agency, no filler
   - no em dashes, no semicolons
   - never "you might like" / "I thought you'd find this interesting"
   - lead with the fact, not the framing

2. SILENCE - the finding is generic, stale, redundant, doesn't actually
   answer the move's hypothesis, OR is something the user could have
   predicted from their profile (no surprise). Explain why in one short
   sentence (for the trace).

CRITICAL surprise check: would a smart reader of the user's own profile
have already known this? If yes, SILENCE - Donna pinging known facts is
worse than not pinging at all.

Default to SILENCE when uncertain. Sending a weak ping costs more than
missing one - Donna's silence is part of the contract.

Respond with the structured schema. ``draft`` is required when decision
is ``send`` and ignored otherwise. ``reason`` is required when decision
is ``silence`` and ignored otherwise."""


class _JudgeOut(BaseModel):
    decision: str = Field(description="'send' or 'silence'")
    draft: str = Field(default="", description="message draft when send; empty when silence")
    reason: str = Field(default="", description="why silenced; empty when send")


# ---------------------------------------------------------------------------
# verdict type
# ---------------------------------------------------------------------------


from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeVerdict:
    decision: JudgeDecision
    draft: str = ""
    reason: str = ""


def _silence(reason: str) -> JudgeVerdict:
    return JudgeVerdict(decision="silence", reason=reason[:_MAX_REASON_CHARS])


# ---------------------------------------------------------------------------
# context formatter
# ---------------------------------------------------------------------------


def _summarize_payload(result: ProactiveResult) -> str:
    """Pull the most useful bits of the result into a flat string.

    The judge doesn't need the raw Exa JSON — just enough signal to
    decide if the finding is worth shipping.
    """
    if result.payload is None:
        return "(no payload)"
    if not isinstance(result.payload, dict):
        return str(result.payload)[:1000]

    # /search and /findSimilar shape: {"results": [...]}
    results = result.payload.get("results")
    if isinstance(results, list) and results:
        lines: list[str] = []
        for i, r in enumerate(results[:5], start=1):
            url = str(r.get("url", "")).strip()
            title = str(r.get("title", "")).strip() or url
            highlights = r.get("highlights") or []
            snippet = ""
            if isinstance(highlights, list) and highlights:
                snippet = " | ".join(str(h).strip() for h in highlights[:2])
            elif r.get("text"):
                snippet = str(r.get("text"))[:300]
            published = str(r.get("publishedDate") or "").strip()
            line = f"[{i}] {title}\n    url: {url}"
            if published:
                line += f"\n    published: {published}"
            if snippet:
                line += f"\n    snippet: {snippet[:300]}"
            lines.append(line)
        return "\n".join(lines)

    # /research, /websets, /monitors return persistence-shaped payloads.
    if "id" in result.payload:
        return f"resource id: {result.payload.get('id')} status={result.payload.get('status', 'unknown')}"

    return str(result.payload)[:1000]


def _format_judge_context(
    *,
    context: ProactiveContext,
    move: ProactiveMove,
    result: ProactiveResult,
) -> str:
    parts: list[str] = []
    if context.current_datetime:
        parts.append(f"Current local time: {context.current_datetime}")
    if context.profile_blurb.strip():
        parts.append(f"## Living Profile\n{context.profile_blurb.strip()}")
    if context.situation_brief.strip():
        parts.append(f"## Situation Brief\n{context.situation_brief.strip()}")
    if context.recent_thread.strip():
        parts.append(f"## Recent thread\n{context.recent_thread.strip()}")
    parts.append(
        "## Proactive move\n"
        f"tool: {move.tool}\n"
        f"query: {move.query}\n"
        f"hypothesis: {move.hypothesis}\n"
        f"user_signal: {move.user_signal}\n"
        f"payoff_if_hit: {move.payoff_if_hit}\n"
        f"rationale (legacy): {move.rationale}\n"
        f"urgency: {move.urgency}\n"
        f"render_hint: {move.render_hint}"
    )
    parts.append(
        "## Result\n"
        f"status: {result.status}\n"
        f"elapsed_ms: {result.elapsed_ms}\n"
        f"{_summarize_payload(result)}"
    )
    parts.append("Decide: SEND with a draft, or SILENCE with a one-line reason.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


async def judge_result(
    *,
    context: ProactiveContext,
    result: ProactiveResult,
    model: str = _MODEL,
) -> JudgeVerdict:
    """Decide if a single result earns a ping. Defaults to silence on error."""
    move = result.move

    # Cheap pre-checks: if the move never returned anything, no point asking.
    if result.status in {"no_hits", "skipped"}:
        return _silence(f"executor status: {result.status}")
    if result.status == "degraded":
        return _silence(f"executor degraded: {result.skipped_reason or 'unknown'}")

    user_block = _format_judge_context(context=context, move=move, result=result)
    try:
        out = await call_structured(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_block,
            schema=_JudgeOut,
            max_tokens=900,
            cache=True,
        )
    except Exception:
        logger.exception("judge_result: call_structured raised")
        return _silence("judge unavailable")

    if out is None:
        return _silence("judge returned no decision")

    decision = (out.decision or "").strip().lower()
    if decision == "send":
        draft = (out.draft or "").strip()
        if not draft:
            return _silence("judge said send but draft was empty")
        return JudgeVerdict(decision="send", draft=draft[:_MAX_DRAFT_CHARS])
    if decision == "silence":
        reason = (out.reason or "").strip() or "judge silenced"
        return _silence(reason)
    return _silence(f"unknown decision: {decision!r}")


async def judge_results(
    *,
    context: ProactiveContext,
    results: list[ProactiveResult],
    model: str = _MODEL,
) -> list[tuple[ProactiveResult, JudgeVerdict]]:
    """Judge each result. Order preserved. Per-result errors silenced.

    Sequential by design — the per-turn move count is small and we want
    deterministic ordering for the trace.
    """
    out: list[tuple[ProactiveResult, JudgeVerdict]] = []
    for r in results:
        verdict = await judge_result(context=context, result=r, model=model)
        out.append((r, verdict))
    return out
