"""Ambitious query generation: reads the full Living Profile + chats +
observations + open_loops and asks Haiku for 8-15 search-shaped queries
across 8 distinct angles.

The current deriver in ``backend/web/proactive/watch_synth.py`` outputs
0-5 watches at coarse "topic" granularity. That under-uses the rich
signal in the LP — a stable user has 10+ angles worth watching at any
given time.

System B generates queries directly, not topics. Each query has:
  - search-shaped text (named entities, time-bound, problem-specific)
  - angle: which kind of search this is
  - cadence: daily/weekly/monthly based on topic velocity
  - ties_to: the LP signal that justifies this query

Designed for QUALITY > brevity. Cost-controlled by:
  - Single Haiku call per derive cycle (not per query)
  - Cadence-aware downstream poller (daily queries don't all fire daily —
    they fire on their own clocks)
  - Dedup at the fetch layer
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from backend.memory.retrieval.structured import call_structured
from db.models import ChatMessage, Observation, OpenLoop, User
from db.session import async_session

logger = logging.getLogger(__name__)


_MODEL = "claude-haiku-4-5-20251001"
_MAX_QUERIES = 12
_MAX_QUERY_CHARS = 280
_MAX_TIES_CHARS = 200


_VALID_ANGLES = frozenset({
    "direct",      # things in user's main work (named entities they own)
    "neighbor",    # specific competitors/peers in the user's space
    "postmortem",  # failures/incidents in adjacent products
    "problem",     # the specific bug class / debug pattern user is on
    "research",    # papers/talks on the user's open intellectual question
    "rhythm",      # health/chronotype/recovery pattern from observations
    "person",      # named individuals from chat or key_people
    "open_loop",   # what's new on a specific commitment user made
})


_VALID_CADENCES = frozenset({"daily", "weekly", "monthly"})

_DEFAULT_CADENCE_BY_ANGLE: dict[str, str] = {
    "direct": "weekly",
    "neighbor": "weekly",
    "postmortem": "weekly",
    "problem": "daily",      # debugging windows are short
    "research": "monthly",   # papers move slowly
    "rhythm": "weekly",
    "person": "weekly",
    "open_loop": "weekly",
}


@dataclass(frozen=True)
class GeneratedQuery:
    """One search-shaped query with provenance."""

    text: str
    angle: str
    cadence: str
    ties_to: str
    expand_with_similar: bool  # whether to /findSimilar on top hit


class _RawQuery(BaseModel):
    text: str = Field(description="search-shaped query string with named entities and time bounds")
    angle: str = Field(description="one of: direct|neighbor|postmortem|problem|research|rhythm|person|open_loop")
    cadence: str = Field(description="daily|weekly|monthly based on how fast the topic moves")
    ties_to: str = Field(description="short quote from LP/chat/loops that justifies this query")
    expand_with_similar: bool = Field(
        default=True,
        description="True for high-value queries where /findSimilar on top hit will surface neighbors worth seeing",
    )


class _QueryGenOut(BaseModel):
    queries: list[_RawQuery] = Field(default_factory=list)


_SYSTEM_PROMPT = """You generate an AMBITIOUS proactive web search plan for a user.

You read their Living Profile (narrative, current_situation, today_shape,
active_tensions, what_changed_this_week, key_people, running_themes),
recent user-side chat messages, observations, and open loops.

You output 8-15 SEARCH-SHAPED queries. Each query is a string you would
type into a search engine to find pages relevant to a SPECIFIC signal in
the inputs. The user gets value from BREADTH — many angles, not many
queries on the same topic.

Hard query rules:
  - SEARCH-SHAPED: like a Google search, not a question. Include named
    entities, products, people, time bounds.
  - SPECIFIC: "Anthropic Claude Agent SDK tool-use loop fallback" beats
    "AI agent SDK". "Poke product launches and pricing changes" beats
    "personal AI products".
  - TIME-BOUND when appropriate: "in the last 30 days", "2026", "Q2 2026".
  - TIED TO A SIGNAL: every query references something concrete in the
    inputs. Quote it in ties_to. No invented topics.

Generate from these 8 distinct ANGLES (mix all that apply, do not force
all 8):

1. direct — things in the user's main work / product. Their stack, the
   APIs they call, the features they're shipping. Use NAMED entities
   from the inputs.
   Example: "Anthropic Claude Agent SDK streaming response interruption recovery"

2. neighbor — specific competitor/peer products, NOT the category. Mine
   chat for product names, founder names. INFERENCE allowed if the user's
   domain makes a peer obvious (a WhatsApp-native AI builder should hear
   about Poke without needing to explicitly mention it).
   Example: "Poke Limitless Friend Granola Highlight personal AI agent launches 2026"

3. postmortem — failures or reliability incidents in adjacent products.
   The user learns more from a competitor's failure than their success.
   Example: "AI assistant product launch reliability bugs incidents 2026 postmortem"

4. problem — the SPECIFIC bug class or debug pattern the user is wrestling
   with right now (mine current_situation + active_tensions). Frame as
   what someone debugging it would search for.
   Example: "agent memory placeholder fallback context loss debugging Claude SDK"

5. research — academic papers, talks, or technical writing on the user's
   open intellectual question. Use arxiv / acm / specific publication
   names where you can.
   Example: "agent memory architecture context retrieval long-term LLM 2026 arxiv papers"

6. rhythm — tied to the user's SPECIFIC observation pattern: chronotype,
   recovery from a health event, sleep-debt window. Be concrete with
   the time signature.
   Example: "post-gastroenteritis recovery sleep founder 4am chronotype 30 days"

7. person — REAL names from chat or key_people. One query per name. If
   the inputs do not name people, skip this angle entirely (do not invent).
   Example: "Saurabh founder partner offer thread updates 2026"

8. open_loop — what's new on a specific commitment the user mentioned.
   Pull from the open_loops list verbatim where possible.
   Example: "voice attentions WhatsApp implementation production roadmap"

For each query also pick:
  - cadence: daily for fresh news / debugging windows; weekly for most
    named-entity / product / problem queries; monthly for research and
    slow-moving topics.
  - expand_with_similar: True when the top hit would have semantically-
    similar pages worth seeing (research papers, postmortems, neighbor
    products). False for high-volume direct news (tweets, launches) where
    /findSimilar would produce noise.

ANTI-PATTERNS — do NOT emit:
  - Generic news bands ("AI news", "tech industry")
  - Internal-state queries ("user's health", "user's deploy progress")
  - Padding queries to hit 15 — quality over quantity. 8 strong queries
    beats 15 mediocre ones.
  - Queries on Anthropic / OpenAI / WhatsApp at a meta level when the
    user IS BUILDING ON those — they already follow those. Watch them
    only when there's a SPECIFIC bug class or pricing/reliability angle.

Aim for 8-12 queries. Prioritize specificity over count.

Voice: terse, lowercase, no em dashes."""


def _format_user_block(
    profile: dict[str, Any],
    *,
    recent_user_chats: list[str],
    observations: list[str],
    open_loops: list[str],
) -> str:
    """Render LP + raw signals for the query generator."""
    parts: list[str] = []

    for key in (
        "narrative",
        "current_situation",
        "today_shape",
        "situation_brief",
    ):
        raw = profile.get(key)
        if raw is None:
            continue
        # Some LP fields can be dicts in older synthesis outputs; only
        # render the string ones for query generation.
        if not isinstance(raw, str):
            continue
        v = raw.strip()
        if v:
            parts.append(f"## {key.replace('_', ' ').title()}\n{v}")

    for key, label in (
        ("active_tensions", "Active tensions"),
        ("what_changed_this_week", "What changed this week"),
        ("running_themes", "Running themes"),
    ):
        items = profile.get(key) or []
        if isinstance(items, list) and items:
            rendered = "\n".join(f"- {x}" for x in items[:6] if str(x).strip())
            if rendered:
                parts.append(f"## {label}\n{rendered}")

    people = profile.get("key_people") or []
    if isinstance(people, list) and people:
        lines = []
        for p in people[:8]:
            if isinstance(p, dict):
                name = (p.get("name") or "").strip()
                role = (p.get("role") or "").strip()
                dyn = (p.get("current_dynamic") or "").strip()
                if name:
                    lines.append(f"- {name} ({role}): {dyn}".strip())
        if lines:
            parts.append("## Key people\n" + "\n".join(lines))

    if recent_user_chats:
        rendered = "\n".join(
            f"- {c[:240]}" for c in recent_user_chats[:80] if c.strip()
        )
        if rendered:
            parts.append(
                "## Recent user-side chat (mine for named entities, "
                "products, people, problems)\n" + rendered
            )

    if observations:
        rendered = "\n".join(
            f"- {o[:200]}" for o in observations[:15] if o.strip()
        )
        if rendered:
            parts.append("## Recent observations\n" + rendered)

    if open_loops:
        rendered = "\n".join(
            f"- {l[:200]}" for l in open_loops[:10] if l.strip()
        )
        if rendered:
            parts.append("## Open loops (commitments user has made)\n" + rendered)

    if not parts:
        parts.append("(empty profile)")

    parts.append(
        "Generate 8-15 ambitious search-shaped queries. Each must tie "
        "to a SPECIFIC signal above. Quality over count."
    )
    return "\n\n".join(parts)


def _coerce_query(raw: _RawQuery) -> GeneratedQuery | None:
    text = (raw.text or "").strip()
    if not text:
        return None
    angle = (raw.angle or "").strip().lower()
    if angle not in _VALID_ANGLES:
        angle = "direct"
    cadence = (raw.cadence or "").strip().lower()
    if cadence not in _VALID_CADENCES:
        cadence = _DEFAULT_CADENCE_BY_ANGLE.get(angle, "weekly")
    return GeneratedQuery(
        text=text[:_MAX_QUERY_CHARS],
        angle=angle,
        cadence=cadence,
        ties_to=(raw.ties_to or "").strip()[:_MAX_TIES_CHARS],
        expand_with_similar=bool(raw.expand_with_similar),
    )


async def generate_ambitious_queries(
    user_id: str,
    *,
    max_queries: int = _MAX_QUERIES,
    model: str = _MODEL,
) -> list[GeneratedQuery]:
    """Read user state, return 0-N ambitious search queries.

    Empty list is valid (a brand-new user with no chat). Never raises;
    returns [] on any failure path.
    """
    async with async_session() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is None:
            return []
        profile = dict(u.living_profile or {})

        chat_rows = (
            await session.execute(
                select(ChatMessage.content)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.role == "user",
                    ChatMessage.is_shadow.is_(False),
                )
                .order_by(desc(ChatMessage.created_at))
                .limit(200)
            )
        ).all()
        recent_chats = [str(r[0] or "").strip() for r in chat_rows if r[0]]
        recent_chats = [c for c in recent_chats if c]

        obs_rows = (
            await session.execute(
                select(Observation)
                .where(Observation.user_id == user_id)
                .order_by(desc(Observation.event_time))
                .limit(20)
            )
        ).scalars().all()
        observations: list[str] = []
        for o in obs_rows:
            raw = (o.raw or "").strip()
            if raw:
                observations.append(f"[{o.type}] {raw}")
                continue
            fields_summary = ", ".join(
                f"{k}={v}" for k, v in (o.fields or {}).items() if v
            )
            if fields_summary:
                observations.append(f"[{o.type}] {fields_summary}")

        loop_rows = (
            await session.execute(
                select(OpenLoop.content)
                .where(OpenLoop.user_id == user_id, OpenLoop.status == "active")
                .order_by(desc(OpenLoop.created_at))
                .limit(15)
            )
        ).all()
        open_loops_text = [str(r[0] or "").strip() for r in loop_rows]
        open_loops_text = [l for l in open_loops_text if l]

    if not profile and not recent_chats and not observations and not open_loops_text:
        return []

    user_block = _format_user_block(
        profile,
        recent_user_chats=recent_chats,
        observations=observations,
        open_loops=open_loops_text,
    )

    try:
        result = await call_structured(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_block,
            schema=_QueryGenOut,
            max_tokens=3000,
            cache=True,
            timeout=30.0,
        )
    except Exception:
        logger.exception(
            "generate_ambitious_queries: call_structured raised user=%s",
            user_id[:8] if user_id else "?",
        )
        return []
    if result is None:
        return []

    out: list[GeneratedQuery] = []
    for raw in (result.queries or [])[: max(0, int(max_queries))]:
        q = _coerce_query(raw)
        if q is not None:
            out.append(q)
    return out
