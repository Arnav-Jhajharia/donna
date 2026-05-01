"""Query creation — the brain of the proactive subsystem.

Reads ``ProactiveContext`` (Living Profile + Situation Brief + recent
thread + current time + trigger + signal queue) and asks Haiku to invent
0-3 ``ProactiveMove`` targets across Exa's surface. The reasoner is
allowed to return zero moves; silence is a valid output.

Contract:
- Never raises. Returns ``[]`` when Haiku is unavailable or the model
  emits nothing usable.
- Validates and clamps every field on the way out - bad ``tool`` strings,
  out-of-range ``urgency``, empty ``query``/``dedup_key`` are dropped.
- All calls degrade through ``call_structured`` (timeout-bounded).

This is intent-based search: Donna decides *what* to look up before the
user asks, anchored in concrete user signals. Vague ('AI news today'),
moralistic ('mindfulness tips'), or unanchored ('something interesting')
moves are explicitly disallowed in the system prompt.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured
from backend.web.proactive.types import (
    VALID_RENDER_HINTS,
    VALID_TOOLS,
    ProactiveContext,
    ProactiveMove,
)

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_RATIONALE_CHARS = 300
_MAX_QUERY_CHARS = 500
_MAX_DEDUP_KEY_CHARS = 120
_MAX_MOVES_DEFAULT = 3


_SYSTEM_PROMPT_BASE = """You decide what Donna should proactively look up for THIS user RIGHT NOW.

You read:
- the user's Living Profile (interests, current obsessions, working context, mentioned people)
- their Situation Brief (open loops, current_status, recent observations)
- their recent thread (last N messages)
- the current local date/time
- the trigger that fired this tick
- the signal queue (pending Exa monitor hits awaiting judgment)

You output 0-3 ProactiveMoves. Each move is one concrete external lookup that
would land for THIS user RIGHT NOW. Zero moves is a valid output - silence is
allowed when nothing in the inputs justifies an interruption.

A great move:
- ties to something the user actually mentioned or is working on
- is fresh (not something they already know or could trivially derive)
- earns the interruption (the user would thank you for surfacing it)
- is specific (a named entity, a clear question - never vague)

A bad move (do NOT emit):
- generic news ("AI news today", "tech news")
- a topic the user has not engaged with
- something the user could have asked themselves
- a moralistic, self-help, or wellness angle
- a recommendation framed as "you might like..."

Each move has SEVEN fields:

1. hypothesis: 1 sentence. What you are *betting* the world contains right now.
   Example: "betting there's a new entrant in maya's wedge that just raised."

2. user_signal: 1 sentence. The concrete thing in the inputs that justifies it.
   Quote or paraphrase. Example: "user said 3d ago they're picking between
   Poke and Limitless for pitch days."

3. payoff_if_hit: 1 sentence. Why the user would thank Donna if a hit comes back.
   Example: "user reacts to news first instead of being surprised at pitch day."

4. tool: pick the right Exa endpoint:
   - "search":       one fact, one shot. Cheapest, fastest.
   - "find_similar": you have a seed URL the user already engaged with.
                     Put the seed URL in `query`.
   - "research":     multi-step synthesis ("how has X evolved over time").
                     Async + expensive - only when one shot won't cut it.
   - "webset":       persistent curated set. Use only for fresh intents
                     not covered by an existing subscription.
   - "monitor":      schedule a recurring search. Almost never the right
                     choice from this loop - subscriptions are managed
                     elsewhere.

5. query:
   - for search/research: an Exa-style query. Neural queries are sentence-shaped
     ("articles comparing the design of X and Y"), not keyword bags.
   - for find_similar: the seed URL exactly.
   - for webset/monitor: the natural-language criteria for the set.

6. urgency: 0..1. 1.0 = today only, 0.5 = this week, 0.1 = whenever.

7. render_hint: short_text | long_text | card | image.

8. dedup_key: stable identifier for the INTENT (not the specific query).
   Same intent fired again should produce the same key.
   Example: "watch:poke_launch", "compare:poke_vs_limitless".

9. rationale: optional 1-2 sentence narrative; treat as legacy. Prefer
   filling hypothesis + user_signal + payoff_if_hit instead.

Rules:
- Anchor every hypothesis in something concretely present in the inputs.
- Do NOT invent user facts. If the inputs don't justify a move, return [].
- Do NOT recommend wellness, mindfulness, or self-help angles.
- Voice: terse, lowercase, no em dashes."""


_TRIGGER_BRANCH_DRAIN = """
TRIGGER: drain.
The signal queue contains pending Exa monitor hits the user has NOT seen.
Your primary job is to silently let those flow downstream - do NOT
generate fresh moves unless you see a gap the queue does not cover.
Return [] if the queue itself is the answer."""

_TRIGGER_BRANCH_MORNING = """
TRIGGER: morning.
The user just entered their first-engage window. Anchor on
``watch_for_tomorrow`` from the Living Profile. Surface ONE sharp move
about the world-state that intersects with what they're watching today."""

_TRIGGER_BRANCH_PRE_EVENT = """
TRIGGER: pre_event.
A calendar event is ~15 minutes away. The user is about to walk in.
Anchor on the people/topic of that event. The move should surface
something they would want to know BEFORE the meeting starts."""

_TRIGGER_BRANCH_MANUAL = """
TRIGGER: manual.
This is a dry-run / debug call. Behave as if it were morning."""


def _system_prompt_for(trigger: str) -> str:
    branch = {
        "drain": _TRIGGER_BRANCH_DRAIN,
        "morning": _TRIGGER_BRANCH_MORNING,
        "pre_event": _TRIGGER_BRANCH_PRE_EVENT,
    }.get(trigger, _TRIGGER_BRANCH_MANUAL)
    return f"{_SYSTEM_PROMPT_BASE}\n\n{branch}"


class _RawMove(BaseModel):
    rationale: str = Field(default="", description="legacy free-form 1-2 sentences")
    hypothesis: str = Field(default="", description="what we're betting the world contains")
    user_signal: str = Field(default="", description="concrete signal from inputs")
    payoff_if_hit: str = Field(default="", description="why the user would thank donna")
    tool: str = Field(description="search | find_similar | research | webset | monitor")
    query: str = Field(description="query string, seed URL, or natural-language criteria")
    params: dict[str, Any] = Field(default_factory=dict)
    urgency: float = Field(default=0.5)
    render_hint: str = Field(default="short_text")
    dedup_key: str = Field(description="stable intent identifier, e.g. 'watch:poke_launch'")


class _QueryCreationOut(BaseModel):
    moves: list[_RawMove] = Field(default_factory=list)


def _format_context(ctx: ProactiveContext) -> str:
    parts: list[str] = []
    parts.append(f"Trigger: {ctx.trigger}")
    if ctx.current_datetime:
        parts.append(f"Current local time: {ctx.current_datetime}")
    if ctx.last_proactive_at:
        parts.append(f"Last proactive turn: {ctx.last_proactive_at}")
    if ctx.profile_blurb.strip():
        parts.append(f"## Living Profile\n{ctx.profile_blurb.strip()}")
    if ctx.situation_brief.strip():
        parts.append(f"## Situation Brief\n{ctx.situation_brief.strip()}")
    if ctx.recent_thread.strip():
        parts.append(f"## Recent thread\n{ctx.recent_thread.strip()}")
    if ctx.signal_queue:
        rendered: list[str] = ["## Signal queue (pending monitor hits)"]
        for s in ctx.signal_queue[:8]:
            rendered.append(
                f"- intent={s.intent_key}\n"
                f"  title: {s.title}\n"
                f"  url: {s.url}\n"
                f"  snippet: {s.snippet[:200]}"
            )
        parts.append("\n".join(rendered))
    parts.append(
        "Decide what (if anything) to proactively look up. "
        "Return moves now - zero is allowed."
    )
    return "\n\n".join(parts)


def _coerce_move(raw: _RawMove) -> ProactiveMove | None:
    tool = (raw.tool or "").strip().lower()
    if tool not in VALID_TOOLS:
        return None
    hint = (raw.render_hint or "").strip().lower() or "short_text"
    if hint not in VALID_RENDER_HINTS:
        hint = "short_text"
    query = (raw.query or "").strip()
    if not query:
        return None
    dedup_key = (raw.dedup_key or "").strip()
    if not dedup_key:
        return None
    rationale = (raw.rationale or "").strip()[:_MAX_RATIONALE_CHARS]
    hypothesis = (raw.hypothesis or "").strip()[:_MAX_RATIONALE_CHARS]
    user_signal = (raw.user_signal or "").strip()[:_MAX_RATIONALE_CHARS]
    payoff = (raw.payoff_if_hit or "").strip()[:_MAX_RATIONALE_CHARS]
    try:
        urgency = float(raw.urgency)
    except (TypeError, ValueError):
        urgency = 0.5
    urgency = max(0.0, min(1.0, urgency))
    params = dict(raw.params or {})
    return ProactiveMove(
        rationale=rationale,
        tool=tool,  # type: ignore[arg-type]
        query=query[:_MAX_QUERY_CHARS],
        params=params,
        urgency=urgency,
        render_hint=hint,  # type: ignore[arg-type]
        dedup_key=dedup_key[:_MAX_DEDUP_KEY_CHARS],
        hypothesis=hypothesis,
        user_signal=user_signal,
        payoff_if_hit=payoff,
    )


async def create_proactive_moves(
    context: ProactiveContext,
    *,
    max_moves: int = _MAX_MOVES_DEFAULT,
    model: str = _MODEL,
) -> list[ProactiveMove]:
    """Read user state, return 0-N validated proactive moves."""
    user_block = _format_context(context)
    system_prompt = _system_prompt_for(context.trigger)
    try:
        result = await call_structured(
            model=model,
            system_prompt=system_prompt,
            user_message=user_block,
            schema=_QueryCreationOut,
            max_tokens=1200,
            cache=True,
        )
    except Exception:
        logger.exception("create_proactive_moves: call_structured raised")
        return []
    if result is None:
        return []
    moves: list[ProactiveMove] = []
    for raw in (result.moves or [])[: max(0, int(max_moves))]:
        move = _coerce_move(raw)
        if move is not None:
            moves.append(move)
    return moves
