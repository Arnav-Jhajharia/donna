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
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select

from backend.dashboard.schema import DashboardPlan, PlanUser
from backend.memory.retrieval.structured import call_structured
from backend.memory.tools._open_loop_view import OpenLoopView
from db.models import (
    CalendarEntry,
    ChatMessage,
    DashboardManifest,
    Observation,
    ProceduralRule,
    User,
)
from db.session import async_session
from donna.attention.noise import filter_attentions, filter_open_loops

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
# 12k accommodates 3-page output. See bottom-of-file note.
_TIMEOUT_S = 90.0
# Wider windows than v1 — the composer is the editorial moment, it gets to read.
_OBSERVATIONS_LIMIT = 15
_OBSERVATIONS_HOURS_BACK = 36
_OPEN_LOOPS_LIMIT = 20
_OFFERED_ATTENTIONS_LIMIT = 4
_LIVE_ATTENTIONS_LIMIT = 12
_CHAT_TAIL_LIMIT = 25
_PROCEDURAL_RULES_LIMIT = 15
_CALENDAR_LOOKAHEAD_HOURS = 18
_DEFAULT_TZ = "Asia/Kolkata"
# Tokens grow with the rich brief — bump the ceiling so 3-page plans don't
# truncate. Sonnet 4.6 prompt-caches the system prompt, so the marginal
# cost is small.
_MAX_TOKENS = 12000

# Timezone → city fallback for the hero subtext when User.facts.current_city
# is unset. Keep short — this is a sensible-default table, not a place
# database. Anything not listed falls back to "none".
_TZ_TO_CITY: dict[str, str] = {
    "Asia/Kolkata": "Mumbai",
    "Asia/Calcutta": "Mumbai",
    "Asia/Singapore": "Singapore",
    "Asia/Tokyo": "Tokyo",
    "Asia/Shanghai": "Shanghai",
    "Asia/Hong_Kong": "Hong Kong",
    "Asia/Dubai": "Dubai",
    "Europe/London": "London",
    "Europe/Paris": "Paris",
    "Europe/Berlin": "Berlin",
    "America/New_York": "New York",
    "America/Los_Angeles": "Los Angeles",
    "America/Chicago": "Chicago",
    "America/Toronto": "Toronto",
    "Australia/Sydney": "Sydney",
}


def _resolve_place(user: User) -> str | None:
    """Return a human place string for the hero subtext, or None.

    Priority:
      1. ``user.facts.current_city.value`` if confidence != "low".
      2. Timezone → city fallback table.
      3. None — caller drops the place line and uses ``illustration: 'none'``.
    """
    facts = user.facts or {}
    if isinstance(facts, dict):
        cc = facts.get("current_city") or {}
        if isinstance(cc, dict):
            value = (cc.get("value") or "").strip()
            confidence = (cc.get("confidence") or "").strip().lower()
            if value and confidence != "low":
                return value
    return _TZ_TO_CITY.get(user.timezone or _DEFAULT_TZ)


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

# Plan shape — TWO PAGES (binding)

The dashboard is **two pages**. The user swipes between them. You emit
``pages: [...]`` with exactly two pages, in this order:

## Page 1 · ``id: "now"`` — the editorial read for THIS moment
The cover. Hero-led. Carries the headline read AND the things that are
loud right now: the overdue commitment, the tracker that's behind, the
person on the user's mind, the meeting in 30 min. Restraint is visible
in tone, not in count — pick blocks that share the same gravitational
center as the moment.

Structure:
- ``hero`` (FIRST block, always)
- optional ``note`` (donna's editorial line on the moment)
- **3–5 body archetypes** — the things alive right now, all anchored to
  the moment's thesis. NOT a status page; only blocks that earn the moment.
- ``footer`` with ``kind`` (LAST block)

Page 1 totals **5–7 blocks**. Sparse Page 1 = empty screen below the
footer. Avoid. If a block doesn't make the moment sharper, drop it to
Page 2.

## Page 2 · ``id: "today"`` — the user's six surfaces

Page 2 is organised by **the user's six surfaces of interest**, not by
archetype. Every block on Page 2 carries a ``domain`` field, and the
renderer groups them under sticky rails (one per domain) in this order:

  ``day`` → ``body`` → ``work`` → ``people`` → ``money`` → ``mind``

Domains:
- ``day``    → time / schedule / what's coming next / active pings
- ``body``   → calories / sleep / water / mood / training / weight
- ``work``   → open loops / decisions / drafts / projects / meeting prep / watches / capabilities
- ``people`` → last touch / relationships / people on user's mind
- ``money``  → spend / runway / recurring subs / refunds
- ``mind``   → reflections / patterns / picks / things to think about

For each surface: pick **0–2 blocks** when there's signal, leave it
EMPTY when there isn't. The renderer auto-collapses empty rails to a
single quiet line — so don't fabricate content. Quiet is honest.

Structure:
- ``kicker: "today"`` and an optional one-line ``thesis`` for the page
- Body blocks (5–10 total) — each carrying ``domain`` ∈ {day, body, work, people, money, mind}
- NO hero. NO footer.

REQUIRED on Page 2: a ``c-capability`` block under ``domain: "work"``
(donna's command palette).

## Total budget
- ~12–15 blocks across both pages.
- Page 1: **5–7 blocks** (hero + note + 3–5 body + footer).
- Page 2: 5–8 blocks (operational + relationship + capability).
- Each catalogue archetype appears AT MOST ONCE across the entire plan
  (don't put two ``c-tracker`` blocks anywhere).
- ``c-capability`` is REQUIRED on page 2.

**Do NOT use ``rows`` or ``intro``. Do NOT emit a top-level flat ``blocks``
array. Always emit ``pages: [...]`` with exactly two pages.**

# Names — never fabricate

NEVER invent a person's name. Person names (recipients of drafts, key
people on rails, names in confront / openloop / pick bodies) MUST come
verbatim from one of: the brief's ``## Key people`` section, an
observation, an open loop, a chat message, or an LP narrative
sentence. If you cannot point at a source for a name, write "someone"
or restructure the block. This rule overrides editorial taste.

When the user's data is thin (Day 1) and you'd otherwise need a name,
DROP the block — don't fill it with a placeholder name like "Ali",
"Maya", "Sam", etc. A missing block is honest; a fabricated name reads
as a leak from someone else's life and breaks trust irreversibly.

# Hard rules (the renderer enforces these)

- P-TH1: ``plan.thesis`` is a non-empty sentence — the moment-level read. lowercase, present-tense, anchored to something concrete.
- P-H1: exactly one ``hero`` block, and it is the first block.
- P-F1: exactly one ``footer`` block, and it is the last block.
- P-A1: each catalogue archetype appears AT MOST ONCE per plan. No two trackers, no two reminders, no two anything.
- P-R1: at most ONE high-stakes block per plan: ``c-confront``, ``c-streak``, or ``c-offer variant=hero``. They never co-occur.
- P-T1: ``c-tracker`` items: 1 (variant=hero), 2 (variant=pair), or 3 (variant=borderless). Never more.

# Color discipline (binding — comes from the catalogue spec)

- R-C1: ONE rust per screen, max. Rust is earned by exactly ONE of: ``c-offer variant=hero``, OR a single rust-tinted ``c-tracker`` item, OR ``c-reminder variant=pill``.
- R-OX1: oxblood is reserved for ``c-confront``. Max one ``c-confront`` per plan, ever.
- R-MS1: moss is reserved for ``c-streak`` and quiet-win ``c-quicklog`` chips.

# DEPRECATED legacy block types — DO NOT EMIT

The schema still accepts these for backwards compatibility, but the catalogue replaces them. Never emit any of: ``thesis``, ``whisper``, ``witness``, ``confrontation``, ``celebration``, ``reflection`` (the legacy one), ``open-loops`` (the legacy one), ``weather-of-you``, ``calendar-shape``, ``todo-list``, ``tracker-grid``, ``nudge-grid``, ``permission`` (the legacy one), ``reminders`` (the legacy one), ``tracker-starter``, ``relationship``, ``news-brief``. Use the catalogue equivalent.

# Frame blocks (always present)

## ``hero`` (first block, always)
- ``date``: human date string. e.g. "Wednesday · 22 April" or "Saturday · 9:41 pm".
- ``greeting``: EXACTLY one of "Morning, <name>." / "Afternoon, <name>." /
  "Evening, <name>." / "Late, <name>." Map by local hour: 5–11 → Morning,
  11–17 → Afternoon, 17–22 → Evening, 22–5 → Late. **Never invent
  alternatives** like "Early," "Dawn," "Night," "Hi" — the four labels above
  are the entire vocabulary.
- ``subtext``: place + temperature + weather. e.g. "Mumbai · 28° · haze lifting by ten".
- ``illustration``: **always set, almost always non-none.** Pick by the
  user's current city in the brief:
    - Singapore → ``"singapore"`` (Marina Bay Sands skyline)
    - Mumbai or anything else / unknown → ``"mumbai"`` (default)
  Only use ``"none"`` when the moment really demands no imagery: a death,
  a grief beat, or an explicit "the only job tonight is sleep" plan with
  three blocks total. **Working sessions, dawn debug sprints, and
  ordinary late nights all keep an illustration.**

## ``footer`` (last block, always)
- ``kind: italic`` — warm signoff. text examples: "the day is yours.", "go.", "rest.", "sleep well.", "tomorrow's a new page.", "i'll be here in the morning." Use for evenings, transitions, end-of-page beats.
- ``kind: caps`` — text is always exactly "tap to talk". Use when the screen invites more interaction (tracking, logging, exploring).
- ``kind: mark`` — text is empty string (""). Use for quiet morning + signature moments.

# Note (optional editorial line below the hero)

``note`` is a single sentence in donna's voice. It is the most editorial slot in the plan. Use it when there's one thing to say but no body block is needed (sc01 morning-clear: "call dad before it gets weirder. you told him 'this week' on tuesday — it's been six days.").

- ``kind: editorial`` (default) — borderless italic. Canonical.
- ``kind: bar`` — rust card with left stripe, more pragmatic.
- ``kind: confront`` — oxblood. **Counts as your single confrontation slot — do NOT also include a ``c-confront`` body block.**

When the LP brief contains an ``## Active tensions`` line that IS the
moment (the user opened the dashboard while the tension is live —
mid-deadline, mid-decision), prefer ``note kind=editorial`` here on
Page 1 over a ``c-confront`` body block on Page 2. The tension belongs
above the fold when it's the moment; in the mind rail when it's
ambient.

When the LP brief contains a sharp ``## What changed this week`` line,
``note kind=editorial`` is also where it belongs if the change IS the
moment ("you slept four hours every night this week — and you're
about to do it again."). Otherwise route it to ``c-reflection
variant=card`` on Page 2 mind.

# BODY VOCABULARY — by page

## Page 1 (now) body — moment-anchored, denser

After hero + optional note, pick **3–5 archetypes** for the now-page body.
Each block must earn its place: it has to point at the same center as
the hero+note. No filler.

High-stakes (max one of these per plan, ever):
- ``c-confront variant=quiet`` — the hard truth, alone (oxblood)
- ``c-offer variant=hero`` — the rust ask donna proposes loud
- ``c-streak variant=badge`` — a clean week worth celebrating

Moment-anchored content:
- ``c-prep variant=inline`` — pre-meeting checklist, when the meeting IS the moment
- ``c-pick variant=editorial`` — a slow morning's read or evening's pick
- ``c-person variant=hero`` — one person owns the screen ("kabir lands at six")
- ``c-reminder variant=pill`` — single overdue ping (use editorial when 2+ pings)
- ``c-reminder variant=editorial`` — multiple pings stacked
- ``c-openloop variant=dashed`` — single overdue commitment (use quote for 2+)
- ``c-tracker variant=hero`` — ONE tracker telling tonight's story (e.g. calories
  when the user is mid-meal, sleep when it's late, hydration when dehydrated)
- ``c-quicklog variant=tray`` — log affordance when the moment is "just record this"
- ``c-reflection variant=prompt`` — a question for the night

Page 1 lower bound: hero + note + 3 body + footer (6 blocks). Even on
a quiet evening, surface what's quietly alive — the tally that needs
hydration, the note someone's waiting on. Empty Page 1 = abandoned
screen.

## Page 2 (today) body — by surface, not by archetype

Every block on Page 2 carries a ``domain`` field. The renderer groups
them into sticky rails. Pick blocks that match the surface; if a surface
has no signal in the brief, EMIT NOTHING for that surface — the
renderer auto-collapses to a quiet line.

### domain: ``day``  (time / schedule / pings)
- ``c-schedule variant=column`` / ``variant=strip`` — today's shape, when calendar has events
- ``c-reminder variant=editorial`` — multiple active pings stacked

### domain: ``body``  (calories / sleep / water / mood / training)
- ``c-tracker variant=hero`` (1 item w/ 7-day history) / ``variant=pair`` (2 items) / ``variant=borderless`` (3 items)
- ``c-streak variant=badge`` — a clean week of a body habit
- ``c-quicklog variant=tray`` — 3-cell log surface for body kinds (drank water / had a meal / ORS done)

### domain: ``work``  (loops / decisions / drafts / watches / capabilities)
- ``c-openloop variant=quote`` — active work commitments
- ``c-watch variant=rows`` — things donna has eyes on (1 sentence per signal, not a comma-list)
- ``c-brief variant=newsstand`` (just fired) / ``variant=index`` (briefs donna runs)
- ``c-prep variant=inline`` — meeting prep checklist
- ``c-decision variant=stack`` — deferred decision
- ``c-draft variant=letter`` — drafted message
- ``c-permission variant=editorial`` — integration not connected, with the pitch
- ``c-confront variant=card`` — work-truth that needs naming
- **``c-capability``** (REQUIRED, always under ``domain: "work"``) —
  donna's command palette. 4–8 capabilities from the inventory. The
  ``intent`` MUST be copied verbatim — don't invent capabilities that
  aren't listed.

### domain: ``people``  (last touch / relationship state / drafts to send)
- ``c-person variant=list`` — 2–4 people on user's mind (LP key_people + recent observations + recent chat)
- ``c-draft variant=letter`` — a drafted message to a specific person (also valid under ``work``)

### domain: ``money``  (spend / runway / recurring / refunds)
- ``c-tracker variant=hero`` (single spend tracker) — only one tracker per plan total
- ``c-watch variant=rows`` — money-side watches (refund chasers, subs renewing)
- ``c-quicklog`` — only when the user logs spend manually

### domain: ``mind``  (reflections / picks / patterns / LP narrative)
- ``c-reflection variant=prompt`` — a question for the night
- ``c-reflection variant=card`` — LP "what changed this week" lifted as a reflection
- ``c-pick variant=card`` — saved-for-later (a book, an article)
- ``c-read variant=index`` — reading queue
- ``c-watch variant=rows`` — LP running themes (2–3, ONE sentence each)
- ``c-confront variant=card`` — LP active tension, OR a pattern Donna noticed

### Per-domain counts
- 0–2 blocks per domain when signal exists, 0 when absent
- TOTAL on Page 2: 5–10 blocks across all 6 domains
- ``c-capability`` is REQUIRED under ``work`` — never omit
- A ``c-tracker`` can ONLY appear once per plan (P-T1 still applies)

Quiet rails are honest. Don't fabricate content to fill them.

# Variant rule of thumb (when you've picked an archetype)

The variant is the editorial decision: how loud, how much chrome.

- editorial flavors (default for slow / quiet moments): ``borderless``, ``rows``, ``inline``, ``column``, ``list``, ``editorial``, ``chips``, ``quote``, ``twoline``, ``quiet``, ``prompt``, ``index``
- card / hero flavors (used when emphasis is earned): ``hero``, ``ticker``, ``newsstand``, ``card``, ``strip``, ``badge``, ``pill``, ``tray``, ``letter``, ``tiles``, ``stack``, ``dashed``, ``soft``

**Default to editorial.** Reach for card/hero only when the moment really earns the volume. A morning with three normal trackers wants ``borderless``, not ``hero``. A weekly brief that just fired wants ``newsstand``. A single overdue commitment wants ``c-openloop variant=dashed``.

# Pairing patterns (canonical duos)

When two body blocks make sense together, these are the shapes that recur. Use them when both blocks earn space:

1. ``c-streak`` + ``c-person variant=list`` — celebrate, then surface who matters
2. ``c-reminder variant=pill`` + ``c-quicklog variant=chips`` — ping + log fast
3. ``c-reminder variant=editorial`` + ``c-quicklog variant=tray`` — multi-ping + multi-log
4. ``c-pick`` + ``c-read`` — book + articles
5. ``c-draft`` + ``c-decision`` — close thread, decide next
6. ``c-confront`` + ``c-reflection`` — hard truth + question for the night
7. ``c-openloop`` + ``c-permission`` — show gaps + offer cure

These are NOT mandatory. A single body block is also fine — often better. Restraint is visible.

# Forbidden combos
- ``c-confront`` + ``c-streak`` (oxblood + moss = mood whiplash)
- ``c-confront`` + ``c-offer variant=hero`` (two loud blocks, screen breaks)
- two of any same archetype (each appears once)
- ``note kind=confront`` AND a ``c-confront`` block (one confrontation per plan, ever)

# Voice rule for prose blocks

Notes, watch signals, brief teasers, confrontation bodies, reflection prompts: **one sentence in donna's voice, not a list.** If you have three things to surface briefly, write a sentence: *"i've got eyes on adobe and the poke launch."* — not a ``·``-separated manifest: *"ADBE · poke launch · design sector stocks."*

Lists feel like a database export. Sentences feel like donna paying attention. Always sentences.

# Emotional temperature

The brief may include an ``Emotional temperature: <value>`` line.

- ``stressed`` / ``anxious`` / ``conflicted`` → edit harder. ``hero`` + ``note editorial`` + ``footer italic`` is enough. Do NOT show watches, briefs, or schedules — they amplify load.
- ``focused`` / ``calm`` / ``proud`` / ``hopeful`` → you can show a paired body (``c-pick + c-read``, ``c-streak + c-person``) without overwhelming.
- ``low energy`` / ``flat`` → a single quiet body block. ``note editorial`` or ``c-reflection`` (evening) or ``c-tracker borderless`` (morning, gentle tints).

## Hero-led plan (when warranted)

Sometimes the moment really has only ONE thing to say — sleep, a death, a delivery, a stillness. Then the dashboard is a cover, not a checklist:

```
hero (illustration: 'none', subtext: 'mumbai · 24° · clear')
note editorial: "the only real job tonight is sleep. the loops will still be here. so will donna. so will the principal email."
footer italic: "close your eyes. the watch holds."
```

Three blocks. That's it. No watches, no trackers. Donna has everything else holding for tomorrow; the user sees that just by looking at her plan staying calm.

This shape is rare — most days have more than one thing worth surfacing. But when the moment earns it, take it.

# Living Profile sections (when the brief contains them)

The brief may include slow-changing LP sections. These are donna's
running mental model of the user — what she's been holding for them
across conversations. They're high-signal and editorial. Do NOT let
them sit unrendered.

## ``## Active tensions``
The user's current internal frictions ("wants to ship vs needs to
sleep", "antler deadline vs partner time"). Pick the SHARPEST ONE for
this moment and lift it into a body block.

- canonical → ``c-confront variant=card`` under ``domain: "mind"`` on
  Page 2. ``eyebrow`` = "noticing". ``title`` = the tension in donna's
  voice ("you're choosing the deck over sleep again."). ``body`` = one
  sentence of context, not a list. **Counts as your single confrontation
  slot — see P-R1 / forbidden combos.**
- when the moment is fragile (Emotional temperature stressed/anxious):
  prefer ``note kind=editorial`` on Page 1 instead — softer.

## ``## Running themes``
Patterns donna is watching across weeks ("sleep slipping when antler
gets close", "money anxiety before pitches"). Theme-shaped, not
event-shaped.

- canonical → ``c-watch variant=rows`` under ``domain: "mind"`` on Page 2.
  ``title`` omitted or "themes". Pick **2–3 themes max**, ONE editorial
  sentence each (not a comma-list). ``subject`` = the theme name in the
  user's vocabulary, ``signal`` = donna's read.

## ``## What changed this week``
The week-over-week delta donna would mention if the user asked "what's
different lately?".

- canonical → ``c-reflection variant=card`` under ``domain: "mind"`` on
  Page 2. ``eyebrow`` = "this week". ``prompt`` = the change in donna's
  voice as a reflection question ("you traded gym for the deck three
  days running. is that the trade you meant to make?"). When the change
  is celebratory (clean week, streak landed), use ``c-streak
  variant=badge`` on Page 1 instead.
- alternate → ``note kind=editorial`` on Page 1 when the change IS the
  moment.

## ``## Today shape`` and ``## Watch for tomorrow``
Already covered by ``thesis`` (the page read) and ``c-schedule`` /
``c-watch`` blocks. Don't duplicate.

## ``## Key people``
Already routes via the ``people`` rail and ``c-person variant=list``.
The LP gives you a curated set with last-touch — prefer that over
inferring from chat.

# Offered attentions (when the brief shows them)

When the brief contains ## Offered attentions, these are structures donna proposed and the user has not yet accepted. Each line shows the attention_id, card type, subject, and rationale. Lift them into the plan as a body block.

Routing rules (one OFFERED attention → one body block):
- ``card=tally`` → ``c-offer variant=hero``. ``eyebrow`` = "offer". ``title`` = "let me track <subject>" (or similar imperative). ``rationale`` = the rationale from the brief, in donna's voice. ``ctaAccept`` = "start tracking". ``ctaDismiss`` = "not now".
- ``card=open_loop`` → ``c-openloop variant=dashed`` with a single item. ``commitment`` = the rationale. Set ``overdue: true`` if the rationale implies the loop has aged.
- ``card=ping`` → ``c-reminder variant=pill`` with a single item. ``label`` = the rationale. ``at`` = relative phrasing.
- ``card=brief`` / ``card=prep_doc`` / ``card=event_stream`` → ``c-offer variant=twoline`` (subtler, editorial). ``title`` = subject in donna's voice. ``rationale`` = the rationale. ``ctaAccept`` = "yes" or "do it" or similar.

NEVER invent an attention_id. Only use attention_ids literally present in the ## Offered attentions section. If no offered attentions exist, do not emit ``c-offer`` or ``c-openloop variant=dashed`` blocks (don't fabricate an offer the user never received).

When you DO render an offered-attention block, it earns one of your body slots. A plan with an offer + one normal body block is fine; a plan with an offer alone is also fine when the offer is the moment.

# Live attentions (what donna is currently running)

When the brief contains ## Live attentions, these are structures the user has already accepted and donna is actively running. **You do not have to render all of them.** A dashboard with 8 cards because there are 8 things to surface has failed at editing — that's a status page, not a magazine cover.

Read the moment first (LP narrative + observations + recent loops + local time + day shape). Then pick **at most 2 LIVE attentions that earn screen-space tonight**. The rest you omit. Silence is fine. The user knows they exist; the dashboard isn't an inventory.

How to decide which earn space:
- the LP narrative is your guide. if it says "sleep-deprived, evening" — sleep-shaped attentions earn space, distractions don't.
- prefer attentions with fresh signal (recent observations matching the subject, ticks landing soon, near deadlines).
- prefer attentions the user is currently engaged with over ambient watches.
- a tally that's at 0 and the user clearly isn't logging tonight has not earned its tile.

Routing rules when a LIVE attention DOES earn space:
- ``card=tally`` → fold into a ``c-tracker`` item. **Use the ``state:`` line in the brief as the ONLY source of truth for the value.** If state is present, copy ``value`` and ``target`` directly. If state is ABSENT, render ``value: "—"`` and ``detail: "not yet logged today"`` — NEVER infer numbers from observation strings or food names. Tint by signal: rust if behind a target, amber for utility (calories, spend), moss for quiet wins, paper for steady. Cluster siblings: 1 item = ``variant=hero`` with history; 2 items = ``variant=pair``; 3 items = ``variant=borderless``.
- ``card=ping`` → fold into a ``c-reminder variant=editorial`` item. ``label`` = the title in user-facing voice. ``at`` = relative phrasing.
- ``card=event_stream`` (watches) → fold into a ``c-watch variant=rows`` item. ``subject`` = subject in human form. ``signal`` = ONE editorial sentence in donna's voice (not a comma-list). ``at`` = freshness.
- ``card=brief`` → ``c-brief variant=newsstand`` if it just fired and is unread; otherwise omit.
- ``card=prep_doc`` → ``c-prep variant=inline`` if you can infer a checklist from the rationale; otherwise omit.
- ``card=open_loop`` → fold into ``c-openloop variant=quote`` items.

Style rules:
- when multiple watches collapse into one ``c-watch`` block, use at most 3 items. Each ``signal`` is ONE sentence.
- standing watches with no fresh signal: omit.
- LIVE attentions DO NOT carry accept verbs. The user already accepted them.

When LIVE attentions are present, the plan should feel like donna is **on it** — calm, present-tense, working. Not "here's everything she has running."

# Required top-level fields
- ``id``: any string — the server overwrites it. emit ``"plan:moment"``.
- ``generatedAt``: any ISO-8601 string — the server overwrites it.
- ``user``: ``{"name": "<user name>", "initial": "<first letter>"}`` — server overwrites.
- ``thesis``: the one-sentence read. required. lowercase, present-tense, anchored.
- ``moment``: one of dawn | morning | midday | afternoon | evening | night | late.
- ``blocks``: leave as ``[]`` — catalogue v2 uses ``pages[]`` instead.
- ``pages``: REQUIRED. Two pages: ``[{id:"now",...}, {id:"today",...}]``.

# Thin-signal fallback (Day 1 / sparse-signal users)

If the input brief is thin (no observations, no open loops, no integrations,
no attentions, almost no chat): keep both pages but lead with the recipe
mosaic — Day 1 is an invitation surface, not a status surface.

- Page 1 (now): ``hero`` + ``note`` editorial + ``c-recipe-mosaic`` (5
  recipes, see below) + ``footer``. The mosaic IS the body — don't add
  trackers, openloops, or other body blocks. The recipes are the
  density.
- Page 2 (today): kicker "today" + thesis "still settling in." +
  ``c-permission`` (whichever integration would help most) + REQUIRED
  ``c-capability`` (4–6 baseline capabilities). Most domain rails stay
  empty — this is honest for Day 1.

## ``c-recipe-mosaic`` (CTA surface — two variants)

Each tile is a tap that opens WhatsApp with a pre-filled primer —
donna's tool loop handles the multi-step workflow setup on the
inbound. The server REPLACES the ``items`` you emit with a fresh
selection from the recipe bank that's filtered against the user's
current attentions + connected integrations. So you choose the
variant + eyebrow + title; the items are dynamic.

### variant=mosaic (Day 1 / sparse-signal cover)
Pinterest-style masonry. Required shape:
- ``variant``: ``"mosaic"`` (or omit — that's the default).
- ``eyebrow``: ``"ask me to"`` (canonical).
- ``title``: one editorial sentence with one ``*verb*`` accent
  (asterisks become the rust italic). Example:
  ``"set up something *real* for you."``.
- ``items``: emit ``[]`` — server fills 5 tiles spanning surfaces
  (work / body / day / people / mind), filtered against existing
  state.

When to use the mosaic variant: thin-signal users (no observations,
no live attentions, no integrations connected). It IS the body — no
trackers / watches / openloops on the same page. Once the user has
meaningful state, the LLM should omit the cover and let the rails
carry the day instead.

### variant=chips (Page 2 footer for established users)
Compact horizontal pill row. NOT a hero — sits at the bottom of the
mind rail as "by the way, more I could run for you." Required shape:
- ``variant``: ``"chips"``.
- ``domain``: ``"mind"`` (always).
- ``eyebrow``: ``"more i could run"`` (canonical) or similar.
- ``title``: optional one-line italic context (``"a few you haven't
  started yet"``).
- ``items``: emit ``[]`` — server fills 3-4 chips, gap-filtered AND
  toolkit-gated (skips recipes whose required OAuth isn't connected).

When to use the chips variant: established users (already have at
least one live attention) who might want to expand donna's
coverage. Never on Page 1. Never combined with the mosaic variant —
pick one or zero per plan.

If the server's selector returns zero candidates (every recipe
already running), the block gets dropped entirely. So emitting it is
always safe; it self-cleans when there's nothing to suggest.

Two pages, even when thin. Don't fabricate content; render the surface honestly."""


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


def _format_open_loop(loop: OpenLoopView) -> str:
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


async def _read_live_attentions(user_id: str) -> list[Any]:
    """Pull LIVE attentions — what donna is currently watching/tracking/pinging.

    Test/debug-shape attentions are filtered before the limit so we
    don't waste a slot on noise.
    """
    try:
        from backend.dashboard.state_snapshot import _is_noise_attention_row
        from db.models import AttentionRow

        async with async_session() as session:
            rows = (
                (
                    await session.execute(
                        select(AttentionRow)
                        .where(AttentionRow.user_id == user_id)
                        .where(AttentionRow.status == "live")
                        .order_by(AttentionRow.created_at.desc())
                        .limit(_LIVE_ATTENTIONS_LIMIT * 2)
                    )
                )
                .scalars()
                .all()
            )
        return [
            r for r in rows if not _is_noise_attention_row(r)
        ][:_LIVE_ATTENTIONS_LIMIT]
    except Exception:
        logger.exception("compose_manifest: live attentions fetch failed user_id=%s", user_id)
        return []


def _format_live_attention(attention: Any) -> str:
    payload = getattr(attention, "payload", None) or {}
    spec_dict = payload.get("spec") if isinstance(payload, dict) else None
    if isinstance(spec_dict, dict):
        subject_dict = (
            spec_dict.get("subject")
            if isinstance(spec_dict.get("subject"), dict)
            else {}
        )
        cadence_dict = (
            spec_dict.get("cadence")
            if isinstance(spec_dict.get("cadence"), dict)
            else {}
        )
        card_label = str(
            getattr(attention, "card", None) or spec_dict.get("card") or "?"
        )
        title = str(
            getattr(attention, "title", None) or spec_dict.get("title") or ""
        )
        description = str(spec_dict.get("description") or "")
        subject = str(subject_dict.get("name") or "")
        cadence_type = str(
            getattr(attention, "cadence_type", None)
            or cadence_dict.get("type")
            or "?"
        )
    else:
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

    # Pull rolled-up state if the attention runtime has computed one. This
    # is the truth surface — when present, the LLM is told to use ONLY
    # this number, not infer from observation strings.
    state_line = _format_attention_state(attention)
    if state_line:
        body = f"{body}\n    state: {state_line}"

    return (
        f"[{aid}] card={card_label} subject={subject or '?'} "
        f"cadence={cadence_type} | {body}"
    )


def _format_attention_state(attention: Any) -> str:
    """Render ``current_state`` as a one-line rollup string, or empty."""
    state = getattr(attention, "current_state", None)
    # Fall back to payload-style storage if the in-memory model didn't
    # surface it directly.
    if state is None:
        payload = getattr(attention, "payload", None) or {}
        if isinstance(payload, dict):
            state = payload.get("current_state")
    if not isinstance(state, dict):
        return ""
    rollup = state.get("rollup", "?")
    value = state.get("value")
    target = state.get("target")
    count = state.get("count")
    last_at = state.get("last_event_at")
    bits: list[str] = [f"value={value}"]
    if target:
        bits.append(f"of {int(target) if isinstance(target, (int, float)) else target}")
    if count is not None:
        bits.append(f"({count} entries)")
    if last_at:
        bits.append(f"last {last_at[11:16]}")
    return f"{rollup}: " + " ".join(bits)


def _capability_inventory(user: User) -> list[tuple[str, str, str]]:
    """Return (label, intent, icon) tuples for capabilities donna can offer.

    The list is composed from a baseline (always available) plus integration-
    gated items. The composer's job is to PICK contextual ones — not surface
    all of them on every screen. The brief tells the LLM which are available;
    the LLM curates 3–6 per dashboard based on the moment.
    """
    # Icons MUST be from CatIconName: drop|flame|rupee|envelope|eye|book|link|chev|check|plug|coffee|bowl.
    # Anything outside that set will be rejected by the schema.
    items: list[tuple[str, str, str]] = []
    # Always available
    items.extend(
        [
            ("ask me anything", "donna, ", "eye"),
            ("summarize today", "summarize my day so far", "book"),
            ("remind me later", "remind me at ", "check"),
            ("track something for me", "start tracking ", "eye"),
            ("log a glass", "i drank a glass of water", "drop"),
            ("log a meal", "i just had ", "bowl"),
            ("draft a message to", "draft a message to ", "envelope"),
        ]
    )
    if getattr(user, "has_google", False):
        items.extend(
            [
                ("check my inbox", "check my inbox for anything important", "envelope"),
                ("draft an email to", "draft an email to ", "envelope"),
                ("what's on my calendar", "what's on my calendar today", "eye"),
                ("search my drive for", "search my drive for ", "book"),
            ]
        )
    if getattr(user, "has_github", False):
        items.extend(
            [
                ("what did i ship today", "what did i ship today", "check"),
                ("list my open PRs", "list my open PRs", "link"),
            ]
        )
    return items


def _format_capability_inventory(items: list[tuple[str, str, str]]) -> str:
    lines = [f"- label=\"{lbl}\" intent=\"{intent}\" icon={icon}" for lbl, intent, icon in items]
    return "## Donna's capability inventory (use these for c-capability blocks; pick contextual ones, do NOT list all)\n" + "\n".join(lines)


def _format_integration_state(user: User) -> str:
    has_google = "yes" if getattr(user, "has_google", False) else "no"
    has_github = "yes" if getattr(user, "has_github", False) else "no"
    return (
        "## Integration state\n"
        f"- google (gmail / calendar / drive): {has_google}\n"
        f"- github: {has_github}"
    )


def _format_chat_message(msg: ChatMessage) -> str:
    """Render a single chat message as a transcript line, capped to 200 chars."""
    role = "user" if msg.role == "user" else "donna"
    body = (msg.content or "").replace("\n", " ").strip()
    if len(body) > 200:
        body = body[:197] + "..."
    when = msg.created_at.isoformat()[:19] if msg.created_at else "?"
    proactive = " (proactive)" if msg.is_proactive else ""
    return f"[{when}] {role}{proactive}: {body}"


def _format_procedural_rule(rule: ProceduralRule) -> str:
    """One-line render of a procedural rule. Tier filter is upstream."""
    body = (rule.rule or "").strip()
    if len(body) > 220:
        body = body[:217] + "..."
    return f"- {body}"


def _format_calendar_entry(entry: CalendarEntry) -> str:
    """One-line render of a calendar entry."""
    when = entry.start_time.isoformat()[:16] if entry.start_time else "?"
    title = (entry.title or "(untitled)").strip()
    bits = [f"[{when}] {title}"]
    if entry.location:
        bits.append(f"@ {entry.location}")
    if entry.category:
        bits.append(f"({entry.category})")
    return " ".join(bits)


def _format_living_profile_block(profile: dict[str, Any]) -> list[str]:
    """Render the LP into labelled sections. Returns one or more brief parts."""
    parts: list[str] = []

    # Editorial dial — the system prompt knows what to do with this.
    temperature = (profile.get("emotional_temperature") or "").strip()
    if temperature:
        parts.append(f"Emotional temperature: {temperature}")

    # The narrative is the headline read of the user's life right now.
    narrative = (profile.get("narrative") or profile.get("current_situation") or "").strip()
    if narrative:
        parts.append(f"## Living profile · narrative\n{narrative[:1200]}")

    # Slow-changing, high-signal LP fields. Each formatted as its own section
    # so the composer can anchor blocks to them by name.
    today_shape = (profile.get("today_shape") or "").strip()
    if today_shape:
        parts.append(f"## Today shape\n{today_shape[:600]}")

    watch = profile.get("watch_for_tomorrow")
    if isinstance(watch, list) and watch:
        bullets = "\n".join(f"- {str(w).strip()[:200]}" for w in watch[:6])
        parts.append(f"## Watch for tomorrow\n{bullets}")
    elif isinstance(watch, str) and watch.strip():
        parts.append(f"## Watch for tomorrow\n{watch.strip()[:600]}")

    themes = profile.get("running_themes")
    if isinstance(themes, list) and themes:
        bullets = "\n".join(f"- {str(t).strip()[:160]}" for t in themes[:8])
        parts.append(f"## Running themes\n{bullets}")

    tensions = profile.get("active_tensions")
    if isinstance(tensions, list) and tensions:
        bullets = "\n".join(f"- {str(t).strip()[:200]}" for t in tensions[:6])
        parts.append(f"## Active tensions\n{bullets}")

    people = profile.get("key_people")
    if isinstance(people, list) and people:
        rendered = []
        for p in people[:8]:
            if isinstance(p, dict):
                name = (p.get("name") or "").strip()
                role = (p.get("role") or p.get("relationship") or "").strip()
                last = (p.get("last_touch") or p.get("last_seen") or "").strip()
                bits = [name] if name else []
                if role:
                    bits.append(role)
                if last:
                    bits.append(f"last: {last}")
                rendered.append("- " + " · ".join(bits))
            elif isinstance(p, str):
                rendered.append(f"- {p.strip()[:160]}")
        if rendered:
            parts.append("## Key people\n" + "\n".join(rendered))

    changed = profile.get("what_changed_this_week")
    if isinstance(changed, str) and changed.strip():
        parts.append(f"## What changed this week\n{changed.strip()[:600]}")
    elif isinstance(changed, list) and changed:
        bullets = "\n".join(f"- {str(c).strip()[:200]}" for c in changed[:5])
        parts.append(f"## What changed this week\n{bullets}")

    return parts


def _format_brief(
    *,
    user: User,
    now_local: datetime,
    place: str | None,
    observations: list[Observation],
    open_loops: list[OpenLoopView],
    offered_attentions: list[Any],
    live_attentions: list[Any],
    chat_tail: list[ChatMessage],
    procedural_rules: list[ProceduralRule],
    calendar_entries: list[CalendarEntry],
    last_manifest_thesis: str | None,
    trigger: str,
) -> str:
    """Plaintext brief handed to the LLM. Sectioned, capped per-section."""
    parts: list[str] = []
    name = (user.name or "friend").strip() or "friend"
    parts.append(f"User: {name}")
    parts.append(f"Timezone: {user.timezone or _DEFAULT_TZ}")
    parts.append(f"Local time: {now_local.isoformat()}")
    if place:
        parts.append(f"Place: {place}")
    else:
        parts.append("Place: (unknown — set illustration to 'none' on the hero, drop the place line)")
    parts.append(f"Trigger: {trigger}")

    # Living Profile — full structured read, not just the narrative. Slow-
    # changing fields the composer can anchor blocks to by name.
    profile = user.living_profile or {}
    if isinstance(profile, dict):
        parts.extend(_format_living_profile_block(profile))

    # Integration state — drives Page 3 permission cards + the capability
    # inventory. Knowing what's connected lets the LLM avoid offering
    # capabilities that would 501.
    parts.append(_format_integration_state(user))

    # Capability inventory — the menu the LLM picks from for c-capability blocks.
    parts.append(_format_capability_inventory(_capability_inventory(user)))

    # Procedural rules — what donna has learned about THIS user. Tier 2/3
    # only; Tier 1 (raw) is too noisy.
    if procedural_rules:
        lines = [_format_procedural_rule(r) for r in procedural_rules]
        parts.append("## Procedural rules (what donna has learned about this user)\n" + "\n".join(lines))

    # Calendar — today + tomorrow morning. Often the right anchor for a
    # ``c-schedule`` or ``c-prep`` block.
    if calendar_entries:
        lines = [f"- {_format_calendar_entry(c)}" for c in calendar_entries]
        parts.append("## Calendar (next 18h)\n" + "\n".join(lines))

    # Observations — wider window. The chronological log of what's happened.
    if observations:
        lines = [f"- {_format_observation(o)}" for o in observations]
        parts.append("## Recent observations (last ~36h)\n" + "\n".join(lines))

    # All active open loops, not capped at 5. The composer decides which
    # earn space — the prompt says "anchor or omit."
    if open_loops:
        lines = [f"- {_format_open_loop(l)}" for l in open_loops]
        parts.append("## Active open loops\n" + "\n".join(lines))

    # Live + offered attentions — already in the v1 brief, kept here.
    if live_attentions:
        lines = [f"- {_format_live_attention(a)}" for a in live_attentions]
        parts.append(
            "## Live attentions (currently active — most have NO fresh signal today; omit unless they do)\n"
            + "\n".join(lines)
        )

    if offered_attentions:
        lines = [f"- {_format_offered_attention(a)}" for a in offered_attentions]
        parts.append(
            "## Offered attentions (awaiting user accept)\n" + "\n".join(lines)
        )

    # Recent chat — the freshest signal, ordered oldest → newest.
    if chat_tail:
        lines = [_format_chat_message(m) for m in chat_tail]
        parts.append(
            "## Recent chat (oldest first — this is the most current signal of what's on user's mind)\n"
            + "\n".join(lines)
        )

    # Don't restate yesterday's thesis. Composer should find a new angle.
    if last_manifest_thesis:
        parts.append(
            f"## Previous dashboard thesis (do NOT restate; find a fresh angle or move on)\n"
            f"\"{last_manifest_thesis.strip()[:200]}\""
        )

    parts.append(
        "Compose a DashboardPlan with `pages: [{id:'now'}, {id:'today'}, {id:'hold'}]`. "
        "Hero on page 1 only. Page 3 must include a c-capability block. "
        "Anchor every block to a thread in the LP, a procedural rule, the calendar, "
        "an observation, or recent chat — if you can't anchor it, omit it. "
        "Total ~12–16 blocks across all three pages."
    )
    return "\n\n".join(parts)


async def _read_chat_tail(
    session, user_id: str, limit: int
) -> list[ChatMessage]:
    """Last N non-shadow chat messages, ordered oldest → newest."""
    rows = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .where(ChatMessage.is_shadow == False)  # noqa: E712
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(reversed(list(rows)))


async def _read_procedural_rules(
    session, user_id: str, limit: int
) -> list[ProceduralRule]:
    """Tier 2 / Tier 3 procedural rules only — Tier 1 is raw and noisy."""
    rows = (
        (
            await session.execute(
                select(ProceduralRule)
                .where(ProceduralRule.user_id == user_id)
                .where(ProceduralRule.type.in_(("tier_2", "tier_3", "tier2", "tier3")))
                .order_by(desc(ProceduralRule.last_confirmed_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _read_calendar_window(
    session, user_id: str, now_local: datetime, hours: int
) -> list[CalendarEntry]:
    """Calendar entries starting in [now, now+hours] in user-local time.

    Stored as UTC-naive in DB; we compare in UTC.
    """
    start_utc = now_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = start_utc + timedelta(hours=hours)
    rows = (
        (
            await session.execute(
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.start_time >= start_utc)
                .where(CalendarEntry.start_time <= end_utc)
                .order_by(CalendarEntry.start_time.asc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _read_last_manifest_thesis(session, user_id: str) -> str | None:
    """Pull the thesis from the previous manifest so the composer can avoid restating."""
    row = (
        await session.execute(
            select(DashboardManifest).where(DashboardManifest.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.plan_jsonb, dict):
        return None
    thesis = row.plan_jsonb.get("thesis")
    if isinstance(thesis, str) and thesis.strip():
        return thesis.strip()
    return None


async def _read_inputs(
    user_id: str,
) -> tuple[
    User,
    list[Observation],
    list[OpenLoopView],
    list[ChatMessage],
    list[ProceduralRule],
    list[CalendarEntry],
    str | None,
] | None:
    """Pull all composer inputs in one DB session.

    Returns ``None`` only when the user does not exist or DB is unreachable.
    Individual sub-fetches degrade independently — a missing calendar table
    or empty procedural rules list never blocks the compose.
    """
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                logger.warning("compose_manifest: user_id=%s not found", user_id)
                return None

            now_local = _resolve_now_local(user.timezone)
            obs_cutoff_utc = (
                now_local.astimezone(timezone.utc) - timedelta(hours=_OBSERVATIONS_HOURS_BACK)
            ).replace(tzinfo=None)

            obs_rows = (
                (
                    await session.execute(
                        select(Observation)
                        .where(Observation.user_id == user_id)
                        .where(Observation.event_time >= obs_cutoff_utc)
                        .order_by(Observation.event_time.desc())
                        .limit(_OBSERVATIONS_LIMIT)
                    )
                )
                .scalars()
                .all()
            )

            from backend.memory.tools._open_loop_view import read_open_loops_unified

            loop_rows = await read_open_loops_unified(
                session,
                user_id=user_id,
                statuses=("active",),
                limit=_OPEN_LOOPS_LIMIT,
            )

            chat_tail: list[ChatMessage] = []
            try:
                chat_tail = await _read_chat_tail(session, user_id, _CHAT_TAIL_LIMIT)
            except Exception:
                logger.exception("compose_manifest: chat tail fetch failed user_id=%s", user_id)

            procedural_rules: list[ProceduralRule] = []
            try:
                procedural_rules = await _read_procedural_rules(
                    session, user_id, _PROCEDURAL_RULES_LIMIT
                )
            except Exception:
                logger.exception(
                    "compose_manifest: procedural rules fetch failed user_id=%s", user_id
                )

            calendar_entries: list[CalendarEntry] = []
            try:
                calendar_entries = await _read_calendar_window(
                    session, user_id, now_local, _CALENDAR_LOOKAHEAD_HOURS
                )
            except Exception:
                logger.exception(
                    "compose_manifest: calendar fetch failed user_id=%s", user_id
                )

            last_thesis: str | None = None
            try:
                last_thesis = await _read_last_manifest_thesis(session, user_id)
            except Exception:
                logger.exception(
                    "compose_manifest: last manifest thesis fetch failed user_id=%s", user_id
                )
    except Exception:
        logger.exception("compose_manifest: db read failed user_id=%s", user_id)
        return None

    return (
        user,
        list(obs_rows),
        filter_open_loops(list(loop_rows)),
        chat_tail,
        procedural_rules,
        calendar_entries,
        last_thesis,
    )


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
    (
        user,
        observations,
        open_loops,
        chat_tail,
        procedural_rules,
        calendar_entries,
        last_manifest_thesis,
    ) = inputs
    offered_attentions = _read_offered_attentions(user_id)
    live_attentions = await _read_live_attentions(user_id)

    now_local = _resolve_now_local(user.timezone)
    place = _resolve_place(user)
    brief = _format_brief(
        user=user,
        now_local=now_local,
        place=place,
        observations=observations,
        open_loops=open_loops,
        offered_attentions=offered_attentions,
        live_attentions=live_attentions,
        chat_tail=chat_tail,
        procedural_rules=procedural_rules,
        calendar_entries=calendar_entries,
        last_manifest_thesis=last_manifest_thesis,
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

    # The catalogue v2 spec is two pages. The schema's PageId literal still
    # includes "hold" for back-compat, and the model occasionally emits a
    # third page anyway — drop it. Anything beyond pages[:2] gets trimmed.
    pages = getattr(plan, "pages", None) or []
    pages_changed = len(pages) > 2
    if pages_changed:
        pages = pages[:2]

    # Hero normalization. The model occasionally emits illustration="none"
    # for ordinary dawn/late-night plans (the prompt says "sparingly" and
    # the model over-applies it) and invents greetings outside the four
    # allowed labels ("Early," "Dawn," "Hi"). Both make the dashboard feel
    # like a status screen instead of donna's surface — coerce here so
    # the brand identity holds regardless of LLM drift.
    illustration_default = _illustration_for(user)
    pages = [
        _normalize_hero_block(p, name=name, now_local=now_local, illustration_default=illustration_default)
        for p in pages
    ]

    # Recipe-mosaic post-processing.
    #
    # Whatever the LLM emitted for ``items`` we replace with a fresh
    # selection from the recipe bank, filtered against the user's
    # current attentions + integrations. Stops the model from
    # hallucinating recipe titles + keeps the mosaic useful for
    # established users (who'd otherwise see "track my calories" even
    # after they already started tracking calories).
    #
    # Day 1 path: the model picked variant=mosaic (the default).
    # Established path: the prompt also allows the model to emit a
    # second c-recipe-mosaic with variant=chips on Page 2 mind rail
    # — we honour that and inject 3-4 chip-tile items.
    pages = await _refresh_recipe_blocks(pages, user_id=user_id)

    overrides["pages"] = pages

    return plan.model_copy(update=overrides)


async def _refresh_recipe_blocks(pages: list[Any], *, user_id: str) -> list[Any]:
    """Replace ``c-recipe-mosaic`` items with fresh, gap-filtered picks.

    The LLM emits the BLOCK (variant + eyebrow + title) but we own the
    ITEMS — so the model can't hallucinate titles or include recipes the
    user is already running. Two paths:

      * variant ∈ {None, "mosaic"} → ``select_for_day_one`` (5 tiles)
      * variant == "chips"          → ``select_for_established`` (4 tiles)

    Pages without any c-recipe-mosaic block are returned unchanged. If
    the selector returns 0 candidates (rare — every recipe already
    running) we drop the block entirely so we don't render an empty
    mosaic.
    """
    from backend.dashboard.recipe_selector import (
        recipe_to_item,
        select_for_day_one,
        select_for_established,
    )
    from backend.dashboard.schema import RecipeItem

    refreshed: list[Any] = []
    for page in pages:
        blocks = list(getattr(page, "blocks", None) or [])
        if not blocks:
            refreshed.append(page)
            continue
        new_blocks: list[Any] = []
        for block in blocks:
            if getattr(block, "type", None) != "c-recipe-mosaic":
                new_blocks.append(block)
                continue
            variant = getattr(block, "variant", None) or "mosaic"
            if variant == "chips":
                picks = await select_for_established(user_id, k=4)
            else:
                picks = await select_for_day_one(user_id, k=5)
            if not picks:
                # Drop the block entirely — every recipe is already running.
                continue
            # Hydrate dicts → RecipeItem so the schema's typed list[RecipeItem]
            # gets the right shape (avoids serializer "unexpected dict" warnings
            # downstream).
            items = [RecipeItem.model_validate(recipe_to_item(r)) for r in picks]
            new_blocks.append(block.model_copy(update={"items": items}))
        refreshed.append(page.model_copy(update={"blocks": new_blocks}))
    return refreshed


_VALID_GREETINGS = ("Morning", "Afternoon", "Evening", "Late")
_VALID_ILLUSTRATIONS = ("mumbai", "singapore", "none")
# Map IANA timezone → illustration choice. Anything not listed defaults
# to "mumbai" (the canonical scenery). Add cities here as we render new
# skyline SVGs for them.
_TZ_TO_ILLUSTRATION = {
    "Asia/Singapore": "singapore",
}


def _illustration_for(user: User) -> str:
    tz = (getattr(user, "timezone", None) or "").strip()
    return _TZ_TO_ILLUSTRATION.get(tz, "mumbai")


def _greeting_for(now_local: datetime) -> str:
    h = now_local.hour
    if 5 <= h < 11:
        return "Morning"
    if 11 <= h < 17:
        return "Afternoon"
    if 17 <= h < 22:
        return "Evening"
    return "Late"


def _normalize_hero_block(
    page: Any, *, name: str, now_local: datetime, illustration_default: str
) -> Any:
    """Coerce hero illustration + greeting back into the catalogue contract.

    Pages with three blocks or fewer (the hero-only sleep/grief shape) keep
    whatever illustration the LLM chose. Anything richer than that defaults
    to ``illustration_default`` (picked from user's timezone — "singapore"
    for SG users, "mumbai" otherwise). Empty hero scenery on a real
    working dashboard reads as broken, not restrained.

    Illustration values outside the supported set ("mumbai" / "singapore" /
    "none") get coerced to the timezone default — keeps us safe when the
    schema literal grows but the renderer hasn't shipped the new SVG yet.
    """
    blocks = list(getattr(page, "blocks", None) or [])
    if not blocks:
        return page
    hero = blocks[0]
    if getattr(hero, "type", None) != "hero":
        return page

    updates: dict[str, Any] = {}

    illustration = getattr(hero, "illustration", None)
    if illustration == "none" and len(blocks) > 3:
        updates["illustration"] = illustration_default
    elif illustration not in _VALID_ILLUSTRATIONS:
        updates["illustration"] = illustration_default

    greeting = getattr(hero, "greeting", "") or ""
    label = greeting.split(",", 1)[0].strip() if greeting else ""
    if label not in _VALID_GREETINGS:
        updates["greeting"] = f"{_greeting_for(now_local)}, {name}."

    if not updates:
        return page

    blocks[0] = hero.model_copy(update=updates)
    return page.model_copy(update={"blocks": blocks})
