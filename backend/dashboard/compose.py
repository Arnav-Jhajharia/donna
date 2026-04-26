"""Compose a fresh ``DashboardPlan`` for a user from their current state.

The flow is intentionally linear and best-effort:

1. Read the ``User`` row (name, timezone). Bail out if the user is missing.
2. Pull the last 5 observations and 5 active open loops.
3. Pack everything into a plaintext brief that follows the same shape as
   ``backend.web.proactive.query_creation._format_context``.
4. Hand the brief + the row-based ``DashboardPlan`` Pydantic schema to
   ``call_structured``. Sonnet 4.6 emits one structurally valid plan via
   Anthropic tool-use.
5. Server-overwrite the ``id``, ``generatedAt``, and ``user`` fields —
   never trust the LLM for these.

Failure modes degrade through ``None``: missing user, no API key, timeout,
or schema-parse failure all log + return ``None`` so the caller can move
on without crashing the brain loop. No retry.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.dashboard.schema import DashboardPlan, PlanUser
from backend.memory.retrieval.structured import call_structured
from db.models import Observation, OpenLoop, User
from db.session import async_session
from donna.attention.noise import filter_attentions, filter_open_loops

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 6000
_TIMEOUT_S = 60.0
_OBSERVATIONS_LIMIT = 5
_OPEN_LOOPS_LIMIT = 5
_OFFERED_ATTENTIONS_LIMIT = 4
_LIVE_ATTENTIONS_LIMIT = 12
_DEFAULT_TZ = "Asia/Kolkata"
_PLACE_STUB = "Mumbai · 29° · soft light"


_SYSTEM_PROMPT = """You compose a single ``DashboardPlan`` JSON object for the user's home dashboard.

The dashboard is a calm, paper-toned web surface the user opens on a phone or laptop. It is not WhatsApp — there is no back-and-forth here. The plan you emit is the entire screen for this moment.

# Voice
- lowercase. no em-dashes. no semicolons.
- blunt. high-agency. no filler.
- never say "I understand" or "Great question."
- when she does not know, say so. never fabricate.
- never call her an "AI assistant."

# What "the right thing at the right time" means
- one thesis sentence for THIS moment — not a general reading of the user's life.
- show only what they need to see RIGHT NOW. cut everything else.
- anchor every block in something concretely present in the input brief (an open loop, a recent observation, the time of day). do not invent state.

# Hard rules (the renderer enforces these — break them and the screen looks wrong)
- P-TH1: at most one ``thesis`` block. one is good; zero is fine.
- P-TH2: ``plan.thesis`` must be a non-empty sentence — that's the moment-level read.
- P-H1: at most one ``hero`` block, and only as the first block when present.
- P-R1: at most one ``confrontation`` AND at most one ``celebration`` per plan.
- P-R2: don't put a confrontation and a celebration on the same screen.
- P-D1: total density (sum of block weights) ≤ 12.
- P-T1: a ``tracker-grid`` block has 1–3 items, no more.
- R-C1: at most one ``featured`` variant nudge across the whole plan ("one rust per screen").

# Composition (READ THIS — this is where most plans go wrong)

A dashboard is a magazine layout, not a stack of cards. If every row is one ``full``-width cell, you've built a list. Mix sizes so the eye has rhythm.

## Cell sizes (each row's cells sum to ~1.0 of the row width)
- ``full``       = 1.0   — use only for: hero, calendar-shape, thesis-when-standalone, confrontation, celebration, big todo-list, footer.
- ``three-quarters`` + ``quarter`` = 1.0 — primary + tiny side note.
- ``two-thirds`` + ``third`` = 1.0 — primary + companion. **most common pattern.**
- ``half`` + ``half`` = 1.0 — balanced pair.
- ``third`` + ``third`` + ``third`` = 1.0 — three small tiles in one row. great for: 3 reminders, 3 small nudges, 3 trackers split out.

## Hard composition rules
- prefer ``rows`` (row-based layout) over a flat ``blocks`` array. ``blocks`` may be empty when ``rows`` is populated; the renderer reads ``rows`` first.
- each row's cells must sum to a valid width: 1.0 (a complete row) — never 1.5, never 0.66 alone.
- aim for **at least one mixed-size row per plan**. an entire plan of ``full``-width rows is a regression — you're not using the layout.
- 2-4 rows is the sweet spot. more than 5 rows = density budget is probably blown.
- mobile collapses every row to single-column automatically; you don't have to plan for that.

## Worked examples

### Example A — morning, two open loops, one tracker
```
intro: { kicker: "saturday · 7:30am · mumbai", greetingPrefix: "good morning, ", accent: "Aarav", greetingSuffix: ".", illustrationId: "tea" }
row 1 (title: "three I picked for you"):
    cell two-thirds → todo-list (3 items from open loops)
    cell third      → tracker-grid (1 item: water progress)
row 2 (title: "today's shape"):
    cell full → calendar-shape (the day's slots)
row 3:
    cell half → reminders (2 time-anchored items)
    cell half → nudge-grid (1 featured nudge)
```

### Example B — late night, thin signal, one open loop
```
intro: { kicker: "sunday · 11pm · mumbai", greetingPrefix: "still up, ", accent: "Kai", greetingSuffix: ".", illustrationId: "moon" }
row 1:
    cell full → thesis (one sentence reading the moment)
row 2:
    cell two-thirds → witness (a quiet observation about the user's recent state)
    cell third      → reminders (1 time-anchored item for tomorrow)
row 3:
    cell full → footer ("see you when you wake.")
```

### Example C — midday, board prep, money + body trackers
```
intro: { kicker: "thursday · 1pm · mumbai", greetingPrefix: "good afternoon, ", accent: "Aarav", greetingSuffix: ".", illustrationId: "glass" }
row 1:
    cell full → hero (image-anchored greeting)
row 2 (title: "your body, your money"):
    cell third → tracker-grid item 1
    cell third → tracker-grid item 2
    cell third → tracker-grid item 3
row 3:
    cell two-thirds → todo-list
    cell third      → permission (e.g. connect calendar)
```

## Picking sizes
- a list with 3+ items wants ``two-thirds`` or ``full``.
- a single-number tile (water count, mood) wants ``third`` or ``quarter``.
- a long-form block (witness, confrontation, celebration) wants ``two-thirds`` or ``full``.
- a calendar-shape with multiple slots is almost always ``full``.

## Intro
- always include an ``intro``.
- ``illustrationId`` ∈ {mumbai, tea, book, moon, glass, walk, none}. pick by moment: morning→tea, late→moon, midday→glass, evening→walk, planning→book, place-strong→mumbai.
- prefer ``greetingPrefix`` + ``accent`` + ``greetingSuffix`` over a flat ``greeting``. the accent (the name) renders italic in rust — that's the editorial voice.

# Block kinds you may use (skip the rest for now)
- ``thesis``: one sentence reading of the moment.
- ``witness``: a quiet observation about the user's recent behavior or state.
- ``todo-list``: small list of things to do today, drawn from open loops.
- ``reminders``: time-anchored items.
- ``permission``: ask for a specific permission (e.g. integration connect).
- ``tracker-grid``: 1–3 numeric tiles for habits the user is tracking.
- ``footer``: a short signoff line at the bottom.

Other block kinds exist in the schema (hero, confrontation, celebration, weather-of-you, calendar-shape, news-brief, relationship, nudge-grid, tracker-starter, open-loops, reflection, whisper). They're allowed but use them sparingly — only when the input brief clearly justifies them.

# Voice rule for whispers, witnesses, and any prose block

These blocks carry editorial. **One sentence in donna's voice, not a list.** If you have three things to surface briefly, write a sentence: *"i've got eyes on adobe and the poke launch."* — not a ``·``-separated tools manifest: *"ADBE · poke launch · design sector stocks."*

Lists feel like a database export. Sentences feel like donna paying attention. Always sentences.

# Emotional temperature

The brief may include an ``Emotional temperature: <value>`` line. When it's ``stressed`` / ``anxious`` / ``conflicted``, edit harder — the screen should say ONE calm thing, not surface every active card. A hero block + a footer can be the whole plan when sleep is the only real job tonight. When it's ``focused`` / ``calm`` / ``proud`` / ``hopeful``, you can show more without overwhelming.

The temperature is a guidance signal, not a rule. Read the LP narrative and the time of day with it; the model knows how to balance.

## Hero-led plan (when warranted)

A ``hero`` block is the magazine-cover shape: one big image-anchored greeting that IS the screen. Use it when the moment really has only ONE thing to say:

- temperature is ``stressed`` or ``anxious`` and time is night/late
- a major win or breakdown lands today (LP narrative says so)
- the dashboard would feel busy any other way

Worked example for stressed late night with sleep deprivation:

```
intro: { kicker: "saturday · 10:14pm · mumbai", greetingPrefix: "still up, ", accent: "Arnav", greetingSuffix: ".", illustrationId: "moon" }
row 1:
    cell full → hero (date: "saturday · 10:14pm", greeting: "the only real job tonight is sleep.", subtext: "the loops will still be here. so will donna. so will the principal email. you have run on zero hours since yesterday.", illustration: "none")
row 2:
    cell full → footer ("close your eyes. the watch holds.")
```

Two blocks. That's it. No reminders, no trackers, no whisper. The dashboard is a cover, not a checklist. Donna has everything else holding for tomorrow; the user sees that just by looking at her plan staying calm.

This shape is rare — most days have more than one thing worth surfacing. But when the moment earns it, take it.

# Offered attentions (when the brief shows them)

When the brief contains ## Offered attentions, these are structures donna proposed and the user has not yet accepted. Each line shows the attention_id, card type, subject, and rationale. Lift them into the plan as a tappable card so the user can say yes or no.

Routing rules (one OFFERED attention → one card on the plan):
- ``card=tally`` → emit a ``tracker-starter`` block. ``trackerName`` = subject. ``rationale`` = the rationale from the brief, in your voice. ``cta`` = "start tracking" or similar one-line CTA. ``icon`` = best fit (drop for hydration, bowl for meals, moon for sleep, heart for mood). ``action`` MUST be ``{"v": "accept_attention", "attentionId": "<id from brief>"}``.
- ``card=open_loop`` → emit a single-item ``open-loops`` block with the rationale as the item text. The block does not currently carry an action, so include a ``whisper`` next to it that says one short line about why we're surfacing it. Defer the accept verb for now.
- ``card=ping`` → emit a single-item ``reminders`` block. ``label`` = the rationale.
- ``card=brief`` or ``card=prep_doc`` or ``card=event_stream`` → emit a ``whisper`` block: ``kicker`` = subject, ``body`` = rationale. Defer the accept verb for now.

NEVER invent an attention_id. ONLY use the attention_id values literally present in the ## Offered attentions section. If no offered attentions exist in the brief, do not emit tracker-starter or attention-shaped blocks.

When you DO render an offered-attention card, lead with it on a high-leverage row (full or two-thirds) so the user sees it. Do not stack more than two offered-attention cards on one plan.

# Live attentions (what donna is currently running)

When the brief contains ## Live attentions, these are structures the user has already accepted and donna is actively running. **You do not have to render all of them.** A dashboard with 8 cards because there are 8 things to surface has failed at editing — that's a status page, not a magazine cover.

Read the moment first (LP narrative + observations + recent loops + local time + day shape). Then pick **2 to 4 LIVE attentions that earn screen-space tonight**. The rest you either:
- collapse into a single short "also running" line at the bottom of the plan (one whisper block, plain sentence: "i've also got the SGX brief and the meals tracker on quiet"), or
- omit entirely if they're not material right now. silence is fine. the user knows they exist; the dashboard isn't an inventory.

How to decide which earn space:
- the LP narrative is your guide. if it says "sleep-deprived, evening" — sleep-shaped attentions earn space, distractions don't. if it says "fundraise pressure, tomorrow's principal call" — the prep_doc earns it, the calorie tracker can wait.
- prefer attentions with fresh signal (recent observations matching the subject, ticks landing soon, near deadlines).
- prefer attentions the user is currently engaged with over ambient watches.
- a tally that's at 0 and the user clearly isn't logging tonight has not earned its tile.

Routing rules when an attention DOES earn space (pick the most natural block type):
- ``card=tally`` → ``tracker-grid`` item. ``title`` = subject in human form. ``value`` = latest count from matching observations, or 0 if none. ``unit`` from description. ``progress`` if a target is inferrable. ``icon`` best fit. Cluster siblings (max 3 per grid block).
- ``card=ping`` → ``reminders`` item. ``label`` = title in user-facing voice. ``at`` = relative phrasing if cadence is unclear.
- ``card=event_stream`` (watches) → ``nudge-grid`` item subtle, or fold multiple watches into a single ``whisper``.
- ``card=brief`` → ``nudge-grid`` or ``whisper`` with kicker "weekly read" or similar.
- ``card=prep_doc`` → ``todo-list`` if you can infer a checklist, else ``whisper``.
- ``card=open_loop`` → ``open-loops`` item.

Style rules:
- when multiple watches/briefs collapse into one whisper, write **one editorial sentence in donna's voice**, not a ``·``-separated list. "i've got eyes on adobe and the poke launch — weekly design sector read lands monday." > "ADBE · poke product hunt launch · design sector stocks · SGX/Nifty".
- standing watches feel best on a smaller cell (``third`` or ``half``); trackers on ``two-thirds`` or ``half``.
- do NOT add ``action`` to LIVE-derived blocks. accept verbs apply to OFFERED only.

When LIVE attentions are present, the plan should feel like donna is **on it** — calm, present-tense, working. Not "here's everything she has running."

# Required top-level fields
- ``id``: any string — the server overwrites it. emit something sensible like ``"plan:moment"``.
- ``generatedAt``: any ISO-8601 string — the server overwrites it.
- ``user``: ``{"name": "<user name>", "initial": "<first letter>"}`` — the server overwrites it.
- ``thesis``: the one-sentence read. required.
- ``moment``: one of dawn | morning | midday | afternoon | evening | night | late.
- ``blocks``: an array (may be empty when ``rows`` is set).
- ``rows``: array of rows. preferred surface.
- ``intro``: object with at least ``kicker`` and either ``greeting`` or ``greeting_prefix``/``accent``/``greeting_suffix``.

If the input brief is thin (no observations, no open loops), emit a small plan: an intro + one row with a single ``witness`` or ``thesis`` block. Don't pad."""


def _moment_for(now_local: datetime) -> str:
    """Map local hour to one of the seven ``MomentTag`` values."""
    h = now_local.hour
    if h < 5:
        return "late"
    if h < 7:
        return "dawn"
    if h < 11:
        return "morning"
    if h < 14:
        return "midday"
    if h < 17:
        return "afternoon"
    if h < 20:
        return "evening"
    return "night"


def _format_observation(obs: Observation) -> str:
    when = obs.event_time.isoformat() if obs.event_time else "?"
    fields = obs.fields or {}
    field_str = ", ".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
    raw = (obs.raw or "").strip()
    bits = [f"[{when}] {obs.type}"]
    if field_str:
        bits.append(f"({field_str})")
    if raw:
        bits.append(f'"{raw[:120]}"')
    return " ".join(bits)


def _format_open_loop(loop: OpenLoop) -> str:
    when = loop.created_at.isoformat() if loop.created_at else "?"
    content = (loop.content or "").strip()[:200]
    return f"[{when}] {content}"


def _read_offered_attentions(user_id: str) -> list[Any]:
    """Pull OFFERED attentions for the user from the file store.

    Best-effort. Returns ``[]`` on any failure or when the store has none.
    Test/debug-shape attentions are filtered before the limit so we
    don't waste a slot on noise.
    """
    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore

        rows = AttentionStore().list(user_id=user_id, status=AttentionStatus.OFFERED)
        return filter_attentions(rows)[:_OFFERED_ATTENTIONS_LIMIT]
    except Exception:
        logger.exception("compose_manifest: offered attentions fetch failed user_id=%s", user_id)
        return []


def _format_offered_attention(attention: Any) -> str:
    spec = getattr(attention, "spec", None)
    card = getattr(spec, "card", None)
    card_label = getattr(card, "value", "") or str(card or "?")
    title = getattr(spec, "title", "") if spec else ""
    description = getattr(spec, "description", "") if spec else ""
    subject = (
        getattr(getattr(spec, "subject", None), "name", "") if spec else ""
    )
    aid = str(getattr(attention, "id", "") or "")
    desc = (description or "").strip()[:160]
    body = title or subject or "attention"
    if desc:
        body = f"{body} — {desc}"
    return f"[{aid}] card={card_label} subject={subject or '?'} | {body}"


def _read_live_attentions(user_id: str) -> list[Any]:
    """Pull LIVE attentions — what donna is currently watching/tracking/pinging.

    Test/debug-shape attentions are filtered before the limit so we
    don't waste a slot on noise.
    """
    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore

        rows = AttentionStore().list(user_id=user_id, status=AttentionStatus.LIVE)
        return filter_attentions(rows)[:_LIVE_ATTENTIONS_LIMIT]
    except Exception:
        logger.exception("compose_manifest: live attentions fetch failed user_id=%s", user_id)
        return []


def _format_live_attention(attention: Any) -> str:
    spec = getattr(attention, "spec", None)
    card = getattr(spec, "card", None)
    card_label = getattr(card, "value", "") or str(card or "?")
    title = getattr(spec, "title", "") if spec else ""
    description = getattr(spec, "description", "") if spec else ""
    subject = (
        getattr(getattr(spec, "subject", None), "name", "") if spec else ""
    )
    cadence = getattr(spec, "cadence", None)
    cadence_type = getattr(getattr(cadence, "type", None), "value", "") or "?"
    aid = str(getattr(attention, "id", "") or "")
    desc = (description or "").strip()[:120]
    body = title or subject or "attention"
    if desc:
        body = f"{body} — {desc}"
    return (
        f"[{aid}] card={card_label} subject={subject or '?'} "
        f"cadence={cadence_type} | {body}"
    )


def _format_brief(
    *,
    user: User,
    now_local: datetime,
    observations: list[Observation],
    open_loops: list[OpenLoop],
    offered_attentions: list[Any],
    live_attentions: list[Any],
    trigger: str,
) -> str:
    """Plaintext brief handed to the LLM. Keep it tight."""
    parts: list[str] = []
    name = (user.name or "friend").strip() or "friend"
    parts.append(f"User: {name}")
    parts.append(f"Timezone: {user.timezone or _DEFAULT_TZ}")
    parts.append(f"Local time: {now_local.isoformat()}")
    parts.append(f"Place: {_PLACE_STUB}")
    parts.append(f"Trigger: {trigger}")

    # Emotional read from the nightly Living Profile synth. Lets the
    # composer dial editorial intensity without code branches: when the
    # synth says the user is stressed/anxious, bias toward fewer cards
    # and a calmer voice. The system prompt has the policy.
    profile = user.living_profile or {}
    if isinstance(profile, dict):
        temperature = (profile.get("emotional_temperature") or "").strip()
        if temperature:
            parts.append(f"Emotional temperature: {temperature}")
        narrative = (profile.get("narrative") or profile.get("current_situation") or "").strip()
        if narrative:
            parts.append(f"Living profile read: {narrative[:600]}")

    if observations:
        lines = [f"- {_format_observation(o)}" for o in observations]
        parts.append("## Recent observations\n" + "\n".join(lines))
    else:
        parts.append("## Recent observations\n(none)")

    if open_loops:
        lines = [f"- {_format_open_loop(l)}" for l in open_loops]
        parts.append("## Active open loops\n" + "\n".join(lines))
    else:
        parts.append("## Active open loops\n(none)")

    if live_attentions:
        lines = [f"- {_format_live_attention(a)}" for a in live_attentions]
        parts.append(
            "## Live attentions (currently active — render these as cards)\n"
            + "\n".join(lines)
        )

    if offered_attentions:
        lines = [f"- {_format_offered_attention(a)}" for a in offered_attentions]
        parts.append(
            "## Offered attentions (awaiting user accept)\n" + "\n".join(lines)
        )
    # No "(none)" for attentions — silent absence keeps the brief tight.

    parts.append(
        "Compose a single DashboardPlan for this moment. "
        "Prefer rows[] + intro. Keep density ≤ 12."
    )
    return "\n\n".join(parts)


async def _read_inputs(
    user_id: str,
) -> tuple[User, list[Observation], list[OpenLoop]] | None:
    """Pull the User row + recent observations + active open loops in one session.

    Returns ``None`` when the user does not exist or the DB is unreachable —
    the caller treats this as a soft failure and skips the compose.
    """
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                logger.warning("compose_manifest: user_id=%s not found", user_id)
                return None

            obs_rows = (
                (
                    await session.execute(
                        select(Observation)
                        .where(Observation.user_id == user_id)
                        .order_by(Observation.event_time.desc())
                        .limit(_OBSERVATIONS_LIMIT)
                    )
                )
                .scalars()
                .all()
            )

            loop_rows = (
                (
                    await session.execute(
                        select(OpenLoop)
                        .where(OpenLoop.user_id == user_id)
                        .where(OpenLoop.status == "active")
                        .order_by(OpenLoop.created_at.desc())
                        .limit(_OPEN_LOOPS_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
    except Exception:
        logger.exception("compose_manifest: db read failed user_id=%s", user_id)
        return None

    return user, list(obs_rows), filter_open_loops(list(loop_rows))


def _resolve_now_local(tz_name: str | None) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name or _DEFAULT_TZ))
    except Exception:
        return datetime.now(ZoneInfo(_DEFAULT_TZ))


async def compose_manifest(
    *, user_id: str, trigger: str
) -> DashboardPlan | None:
    """Compose one ``DashboardPlan`` for ``user_id``. Best-effort.

    Server overrides ``id``, ``generated_at``, and ``user`` after parse —
    never trust the LLM for identity fields.
    """
    inputs = await _read_inputs(user_id)
    if inputs is None:
        return None
    user, observations, open_loops = inputs
    offered_attentions = _read_offered_attentions(user_id)
    live_attentions = _read_live_attentions(user_id)

    now_local = _resolve_now_local(user.timezone)
    brief = _format_brief(
        user=user,
        now_local=now_local,
        observations=observations,
        open_loops=open_loops,
        offered_attentions=offered_attentions,
        live_attentions=live_attentions,
        trigger=trigger,
    )

    try:
        plan = await call_structured(
            model=_MODEL,
            system_prompt=_SYSTEM_PROMPT,
            user_message=brief,
            schema=DashboardPlan,
            max_tokens=_MAX_TOKENS,
            cache=True,
            timeout=_TIMEOUT_S,
        )
    except Exception:
        logger.exception("compose_manifest: call_structured raised user_id=%s", user_id)
        return None

    if plan is None:
        logger.warning(
            "compose_manifest: structured call returned None user_id=%s trigger=%s",
            user_id,
            trigger,
        )
        return None

    name = (user.name or "friend").strip() or "friend"
    server_now = now_local.isoformat()
    overrides: dict[str, Any] = {
        "id": f"plan:{user_id}:{server_now}",
        "generated_at": server_now,
        "user": PlanUser(name=name, initial=name[:1].upper()),
    }
    if not getattr(plan, "moment", None):
        overrides["moment"] = _moment_for(now_local)

    return plan.model_copy(update=overrides)
