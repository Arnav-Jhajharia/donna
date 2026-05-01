"""External watch derivation - the fanout from user state to search queries.

Given a user's Living Profile, asks Haiku: 'what should we watch on the
external web for this user?' Outputs 0-N search-shaped topics, each from
a distinct angle (product space, named entity, thesis, news domain,
technical). Empty list is a valid output - a user in an internal-focused
phase shouldn't have noise piped at them.

This is the creative act of the proactive subsystem. The judge later
filters for "is THIS hit worth surfacing". This function decides "what
topics is it even worth watching for THIS user RIGHT NOW".
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
_MAX_WATCHES = 5
_MAX_DESCRIPTION_CHARS = 240
_MAX_RATIONALE_CHARS = 240


_SYSTEM_PROMPT = """You decide what topics Donna should subscribe to on the
external web for THIS user.

You read the user's Living Profile (narrative, current_situation,
active_tensions, what_changed_this_week, key_people, running_themes,
today_shape).

You output 0-5 watch topics. Each watch must come from a DISTINCT angle:

- product_space: a market or product category the user is competing in,
  studying, or evaluating
- named_entity: a specific person, company, or organization the user
  orbits and would want news about
- thesis: an intellectual question or framework the user is actively
  thinking through (e.g., "narrow wedge case studies", "AI infra moat
  erosion")
- news_domain: an industry beat, region, or regulatory area that
  matters to their work
- technical: a specific technology, library, API, or protocol they're
  building on or evaluating

Each watch has three fields:

- description: a SEARCH-SHAPED string. Hard rules:
    * Sentence-shaped, not a keyword bag. Exa runs neural search; it
      wants natural-language phrasing.
    * Named entities or proper nouns are required when the inputs
      mention them. "Poke updates and product launches" beats
      "personal AI agents". "Anthropic Claude API outages and pricing
      changes" beats "Claude API reliability updates SDKs".
    * No duplicated terms. No comma-bag of keywords.
    * Mine the recent chat and observations for ACTUAL named entities
      the user has mentioned. Specific names beat category labels.
    * NOT internal hooks like "did user hit deploy on time" or "check
      on user's stomach health". Donna will hand this string to Exa as
      a webset query - if the string would not return useful pages on
      Google, do not emit it.

- rationale: 1 sentence quoting or paraphrasing the SPECIFIC signal in
  the inputs that justifies the watch. Example: "user mentioned in
  active_tensions they're picking between Poke and Limitless for pitch
  days."

- angle: which of the 5 categories above.

A great watch:
- ties to a CONCRETE signal in the inputs (a person mentioned, a topic
  brought up, a market the user is in)
- has public web traces Exa can find (named entities, real products,
  public events)
- is something the user would thank Donna for surfacing, not creepy
  or obvious

A bad watch (do NOT emit):
- generic news bands ("AI news", "tech industry", "startup news")
- internal-state monitoring ("user's health", "user's deploy progress",
  "did the user sleep enough")
- a topic the user has not actually engaged with in the inputs
- vague abstractions without a named entity
- self-help, wellness, mindfulness angles
- anything you have to invent or pad to fill a slot

CRITICAL distinction: separate ACUTE state from DURABLE interests.

- Acute state = what the user is dealing with TODAY (a health crunch, a
  deploy, a family event, a fight). This is internal and short-lived.
  Acute state alone is NOT a reason to return [].

- Durable interests = the work they do, the products they build, the
  markets they care about, the people they orbit, the technologies
  they're invested in. These persist across acute states.

Read the inputs for DURABLE signals first. The narrative usually says
what the user is durably building or thinking about ("user is building
X", "user is investing in Y", "user runs Z"). The active_tensions and
what_changed_this_week mostly capture acute state. The current_situation
mixes both - read carefully.

Example: a user in a health-and-deploy crunch (acute) who is durably
building a personal AI product (durable) should still get watches on
the personal AI / agent product space, the APIs they build on
(Anthropic, Exa), and competitor products. The acute health state is
not a watch target. The durable build space is.

Return [] only when there is genuinely no durable external interest in
the inputs. Empty is valid. Silence is valid. Padding is worse than
silence. But silence on a user with clear durable work is a failure -
they should be hearing about their space.

Distinct-angle rule: do NOT emit two watches in the same angle category
unless the inputs genuinely justify two distinct named entities in that
angle. One watch per angle is the default.

Voice: terse, lowercase, no em dashes."""


class _RawWatch(BaseModel):
    description: str = Field(description="search-shaped topic, named entities preferred")
    rationale: str = Field(description="quoted or paraphrased user signal")
    angle: str = Field(description="product_space|named_entity|thesis|news_domain|technical")


class _WatchSynthOut(BaseModel):
    watches: list[_RawWatch] = Field(default_factory=list)


_VALID_ANGLES = frozenset({
    "product_space", "named_entity", "thesis", "news_domain", "technical"
})


@dataclass(frozen=True)
class DerivedWatch:
    """One external watch with provenance."""

    description: str
    rationale: str
    angle: str


def _format_living_profile(
    profile: dict,
    *,
    recent_user_chats: list[str] | None = None,
    observations: list[str] | None = None,
    open_loops: list[str] | None = None,
) -> str:
    """Render Living Profile + recent raw signals for the deriver.

    Living Profile is a lossy summary; the deriver also gets recent
    chat snippets and observations so it can mine actual named entities
    the user has mentioned.
    """
    parts: list[str] = []

    narrative = (profile.get("narrative") or "").strip()
    if narrative:
        parts.append(f"## Narrative\n{narrative}")

    current = (profile.get("current_situation") or "").strip()
    if current:
        parts.append(f"## Current situation\n{current}")

    today = (profile.get("today_shape") or "").strip()
    if today:
        parts.append(f"## Today shape\n{today}")

    tensions = profile.get("active_tensions") or []
    if isinstance(tensions, list) and tensions:
        rendered = "\n".join(f"- {t}" for t in tensions[:6] if str(t).strip())
        if rendered:
            parts.append(f"## Active tensions\n{rendered}")

    changes = profile.get("what_changed_this_week") or []
    if isinstance(changes, list) and changes:
        rendered = "\n".join(f"- {c}" for c in changes[:6] if str(c).strip())
        if rendered:
            parts.append(f"## What changed this week\n{rendered}")

    people = profile.get("key_people") or []
    if isinstance(people, list) and people:
        rendered_lines: list[str] = []
        for p in people[:8]:
            if isinstance(p, dict):
                name = (p.get("name") or "").strip()
                role = (p.get("role") or "").strip()
                dyn = (p.get("current_dynamic") or "").strip()
                if name:
                    rendered_lines.append(f"- {name} ({role}): {dyn}".strip())
        if rendered_lines:
            parts.append("## Key people\n" + "\n".join(rendered_lines))

    themes = profile.get("running_themes") or []
    if isinstance(themes, list) and themes:
        rendered = "\n".join(f"- {t}" for t in themes[:6] if str(t).strip())
        if rendered:
            parts.append(f"## Running themes\n{rendered}")

    if recent_user_chats:
        rendered = "\n".join(
            f"- {c[:240]}" for c in recent_user_chats[:25] if c.strip()
        )
        if rendered:
            parts.append(
                "## Recent user-side chat (mine these for named entities)\n"
                + rendered
            )

    if observations:
        rendered = "\n".join(
            f"- {o[:200]}" for o in observations[:12] if o.strip()
        )
        if rendered:
            parts.append("## Recent observations\n" + rendered)

    if open_loops:
        rendered = "\n".join(
            f"- {l[:200]}" for l in open_loops[:8] if l.strip()
        )
        if rendered:
            parts.append("## Open loops\n" + rendered)

    if not parts:
        parts.append("(empty profile)")

    parts.append(
        "Decide what (if anything) Donna should subscribe to on the external "
        "web for this user. Return 0-5 watches. Empty is valid. Prefer "
        "named entities you can see in the chat / observations / open loops "
        "over abstract category labels."
    )
    return "\n\n".join(parts)


def _coerce_watch(raw: _RawWatch) -> DerivedWatch | None:
    desc = (raw.description or "").strip()
    if not desc:
        return None
    rat = (raw.rationale or "").strip()
    angle = (raw.angle or "").strip().lower()
    if angle not in _VALID_ANGLES:
        angle = "product_space"
    return DerivedWatch(
        description=desc[:_MAX_DESCRIPTION_CHARS],
        rationale=rat[:_MAX_RATIONALE_CHARS],
        angle=angle,
    )


async def derive_external_watches(
    user_id: str,
    *,
    max_watches: int = _MAX_WATCHES,
    model: str = _MODEL,
) -> list[DerivedWatch]:
    """Read the user's Living Profile, return 0-N external watches.

    Empty list is a valid output. Never raises - returns [] on any
    failure path so the caller can proceed without proactive web
    subscriptions for users where signal is thin.
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
                .limit(30)
            )
        ).all()
        recent_chats = [str(r[0] or "").strip() for r in chat_rows]
        recent_chats = [c for c in recent_chats if c]

        obs_rows = (
            await session.execute(
                select(Observation)
                .where(Observation.user_id == user_id)
                .order_by(desc(Observation.event_time))
                .limit(15)
            )
        ).scalars().all()
        observations: list[str] = []
        for o in obs_rows:
            raw = (o.raw or "").strip()
            if raw:
                observations.append(f"[{o.type}] {raw}")
                continue
            fields_summary = ", ".join(f"{k}={v}" for k, v in (o.fields or {}).items() if v)
            if fields_summary:
                observations.append(f"[{o.type}] {fields_summary}")

        loop_rows = (
            await session.execute(
                select(OpenLoop.content)
                .where(OpenLoop.user_id == user_id, OpenLoop.status == "active")
                .order_by(desc(OpenLoop.created_at))
                .limit(10)
            )
        ).all()
        open_loops_text = [str(r[0] or "").strip() for r in loop_rows]
        open_loops_text = [l for l in open_loops_text if l]

    if not profile and not recent_chats and not observations:
        return []

    user_block = _format_living_profile(
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
            schema=_WatchSynthOut,
            max_tokens=1200,
            cache=True,
        )
    except Exception:
        logger.exception(
            "derive_external_watches: call_structured raised user=%s",
            user_id[:8] if user_id else "?",
        )
        return []
    if result is None:
        return []

    out: list[DerivedWatch] = []
    for raw in (result.watches or [])[: max(0, int(max_watches))]:
        w = _coerce_watch(raw)
        if w is not None:
            out.append(w)
    return out
