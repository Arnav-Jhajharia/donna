"""Fake tool surface for Stage 0.5 testing.

Goal: exercise Donna's tool instincts (does she reach for the right tool at
the right moment?) without wiring the real memory/action backends. Every tool
returns small, Arnav-flavored canned payloads so her replies feel real.

Swap in via DonnaAgentConfig.tool_mode = "fake". See options.py.

Tool descriptions deliberately follow Anthropic's writing-effective-tools
guidance: when-to-use, when-NOT-to-use, high-signal return values.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

from claude_agent_sdk import tool

from .tool_logic import text_content

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canned data. Drawn from data.py LIVING_PROFILE so it feels coherent.
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> str:
    return (_NOW - timedelta(days=n)).isoformat(timespec="minutes")


_EPISODIC_SNIPPETS = [
    (_days_ago(2), "arnav said the antler deck still feels flat on market size. said he'd rework slide 4 tonight."),
    (_days_ago(5), "arnav venting about burnout mid-sprint. said he'd sleep early. did not."),
    (_days_ago(7), "last pitch run-through: nervous, rushed the harp story. luca said open with harp, not tam."),
    (_days_ago(10), "arnav asked to remind him to text luca. never followed up."),
    (_days_ago(12), "discussed hero film cuts for donna landing page. picked the one where she interrupts mid-sentence."),
    (_days_ago(21), "arnav said fundraise was stressing him more than the build. first time he said it out loud."),
]

_GRAPH_FACTS = [
    "arnav -> co-founding -> donna (2026 launch)",
    "arnav -> pitching -> antler (in 16h as of last mention)",
    "arnav -> built -> harp (apple vision pro clinical trials, tech-transferred, piloted in hospitals)",
    "harp -> strongest -> pitch hook (per luca, per past reviews)",
    "arnav -> sparring_partner -> luca",
    "arnav -> accountability -> ishmit",
    "arnav -> close_friend -> hridayansh",
    "arnav -> student -> nus (year 2 CS)",
]

_OBSERVATIONS = {
    "expense": [
        {"ts": _days_ago(0), "amount": 6, "currency": "SGD", "note": "coffee"},
        {"ts": _days_ago(1), "amount": 4.5, "currency": "SGD", "note": "coffee"},
        {"ts": _days_ago(2), "amount": 22, "currency": "SGD", "note": "dinner w/ luca"},
        {"ts": _days_ago(3), "amount": 6, "currency": "SGD", "note": "coffee"},
        {"ts": _days_ago(5), "amount": 180, "currency": "SGD", "note": "figma annual"},
    ],
    "mood": [
        {"ts": _days_ago(0), "score": 4, "note": "anxious, pre-antler"},
        {"ts": _days_ago(2), "score": 6, "note": "decent, shipped deck v3"},
        {"ts": _days_ago(5), "score": 3, "note": "burnout, sleep bad"},
        {"ts": _days_ago(7), "score": 5, "note": "pitch rehearsal ok, nerves"},
    ],
    "sleep": [
        {"ts": _days_ago(0), "hours": 5.5, "note": "late night on deck"},
        {"ts": _days_ago(1), "hours": 6, "note": "fine"},
        {"ts": _days_ago(2), "hours": 4, "note": "wired, couldn't sleep"},
    ],
}

_OPEN_LOOPS = [
    {"id": "ol_001", "title": "text luca re pitch order (harp first)", "opened": _days_ago(10), "status": "open"},
    {"id": "ol_002", "title": "rework antler deck slide 4 (market size)", "opened": _days_ago(2), "status": "open"},
    {"id": "ol_003", "title": "reply to ishmit about gym thursday", "opened": _days_ago(1), "status": "open"},
]

_CALENDAR = [
    {"ts": (_NOW + timedelta(hours=16)).isoformat(timespec="minutes"), "title": "antler pitch", "duration_min": 30},
    {"ts": (_NOW + timedelta(days=1, hours=2)).isoformat(timespec="minutes"), "title": "luca 1:1", "duration_min": 45},
    {"ts": (_NOW + timedelta(days=2)).isoformat(timespec="minutes"), "title": "donna hero film review", "duration_min": 60},
]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@tool(
    "recall_episodic",
    (
        "Search episodic memory for past-conversation snippets. "
        "Returns up to 5 dated snippets as plain text. "
        "USE WHEN: the user references something Donna would only know from past turns "
        "('did I tell you about X', 'was I nervous last time', 'what did luca say'). "
        "DO NOT USE: for ambient filler ('haha', 'k'), for things the Living Profile or "
        "current thread already answers, or for anything time-sensitive like today's calendar."
    ),
    {"query": str},
)
async def recall_episodic(args):
    query = str(args.get("query", "")).strip().lower()
    if not query:
        return text_content("no matching memories found.")
    # naive substring rank so it feels responsive to the query
    scored = [(sum(1 for w in query.split() if w in snippet.lower()), ts, snippet)
              for ts, snippet in _EPISODIC_SNIPPETS]
    scored.sort(reverse=True)
    hits = [(ts, s) for score, ts, s in scored if score > 0][:5]
    if not hits:
        hits = random.sample(_EPISODIC_SNIPPETS, 2)
    body = "\n".join(f"[{ts}] {s}" for ts, s in hits)
    return text_content(body)


@tool(
    "recall_graph",
    (
        "Search the user's knowledge graph for relational facts (people, decisions, "
        "commitments). Returns up to 10 lines like 'subject -> relation -> object'. "
        "USE WHEN: the user asks about relationships or roles ('who is luca', 'what's harp'), "
        "or when composing a reply needs to anchor to known entities. "
        "DO NOT USE: for episodic recall, for trackers, or when the Living Profile covers it."
    ),
    {"query": str},
)
async def recall_graph(args):
    query = str(args.get("query", "")).strip().lower()
    if not query:
        return text_content("no graph hits.")
    hits = [f for f in _GRAPH_FACTS if any(w in f for w in query.split())]
    if not hits:
        hits = _GRAPH_FACTS[:3]
    return text_content("\n".join(f"- {h}" for h in hits[:10]))


@tool(
    "smart_recall",
    (
        "Adaptive recall across episodic, graph, and document memory. Returns the top "
        "mixed hits. "
        "USE WHEN: you want the best answer without picking a source (vague questions, "
        "'what did we talk about'). "
        "DO NOT USE: when the question is clearly episodic-only or graph-only — call those "
        "directly. Never call after recall_episodic or recall_graph already ran this turn."
    ),
    {"message": str},
)
async def smart_recall(args):
    msg = str(args.get("message", "")).strip().lower()
    if not msg:
        return text_content("no hits.")
    ep = [s for _, s in _EPISODIC_SNIPPETS if any(w in s.lower() for w in msg.split())][:3]
    gr = [f for f in _GRAPH_FACTS if any(w in f for w in msg.split())][:3]
    lines = [f"(episode) {s}" for s in ep] + [f"(graph) {f}" for f in gr]
    if not lines:
        lines = ["no strong hits across sources."]
    return text_content("\n".join(lines))


@tool(
    "read_tracker",
    (
        "Read recent entries for a named tracker. Known names: 'expense', 'mood', 'sleep'. "
        "Returns a JSON-ish list of recent observations. Accepts optional local-time period "
        "today, yesterday, this_week, or last_week. "
        "USE WHEN: the user asks how much/how often/how they've been feeling ('how much did "
        "I spend', 'was I sleeping ok', 'mood this week'). "
        "DO NOT USE: to log a new entry — use log_observation. Do not use for non-tracker data."
    ),
    {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "period": {"type": "string"},
        },
    },
)
async def read_tracker(args):
    name = str(args.get("name", "")).strip().lower()
    entries = _OBSERVATIONS.get(name, [])
    if not entries:
        return text_content(f"no tracker named '{name}'. known: expense, mood, sleep.")
    lines = [f"- {e}" for e in entries]
    return text_content("\n".join(lines))


@tool(
    "list_observations",
    (
        "List recent observations, optionally filtered by type. Returns the latest 10 entries. "
        "USE WHEN: the user wants a summary view across a tracker ('what have I been spending "
        "on', 'recent moods'). "
        "DO NOT USE: when the user names a single tracker and wants detail — use read_tracker."
    ),
    {"type": str},
)
async def list_observations(args):
    t = str(args.get("type", "")).strip().lower()
    if t and t in _OBSERVATIONS:
        entries = [(t, e) for e in _OBSERVATIONS[t]]
    else:
        entries = [(k, e) for k, lst in _OBSERVATIONS.items() for e in lst]
    entries.sort(key=lambda pair: pair[1]["ts"], reverse=True)
    lines = [f"[{kind}] {e}" for kind, e in entries[:10]]
    return text_content("\n".join(lines) or "no observations.")


@tool(
    "list_open_loops",
    (
        "List the user's currently open loops (unresolved threads awaiting follow-up). "
        "USE WHEN: composing a reply where a pending item might be relevant, or the user "
        "asks 'what am I forgetting'. "
        "DO NOT USE: to open a new loop (use track_open_loop) or close one (close_open_loop)."
    ),
    {},
)
async def list_open_loops(args):
    lines = [f"- {l['id']}: {l['title']} (opened {l['opened']})" for l in _OPEN_LOOPS if l["status"] == "open"]
    return text_content("\n".join(lines) or "no open loops.")


@tool(
    "list_calendar",
    (
        "List upcoming calendar events (next 72h). Returns title, time, duration. "
        "USE WHEN: the user asks about their schedule, or a reply needs to reference what's "
        "coming up (pre-pitch nerves, conflicts). "
        "DO NOT USE: for past events (use recall_episodic) or to create events (no tool yet)."
    ),
    {},
)
async def list_calendar(args):
    lines = [f"- {e['ts']}: {e['title']} ({e['duration_min']}m)" for e in _CALENDAR]
    return text_content("\n".join(lines) or "nothing on the calendar.")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

@tool(
    "log_observation",
    (
        "Record a new observation for a tracker. Returns a confirmation line. "
        "USE WHEN: the user states a fact that belongs to a tracker ('coffee was 6 bucks', "
        "'slept 4 hours', 'feeling like shit today'). "
        "DO NOT USE: for things that aren't trackable data (opinions, plans, meta-chat)."
    ),
    {"type": str, "value": str, "note": str},
)
async def log_observation(args):
    t = str(args.get("type", "")).strip().lower()
    v = str(args.get("value", "")).strip()
    n = str(args.get("note", "")).strip()
    return text_content(f"logged. tracker={t} value={v} note={n or '-'}")


@tool(
    "track_open_loop",
    (
        "Open a new loop to follow up on later. Returns the new loop id. "
        "USE WHEN: the user commits to something future-facing ('remind me to text luca', "
        "'I should reply to mom'), or Donna herself identifies a thread worth holding. "
        "DO NOT USE: for things already scheduled on the calendar, or trivial reminders that "
        "fit a single burst."
    ),
    {"title": str},
)
async def track_open_loop(args):
    title = str(args.get("title", "")).strip() or "untitled"
    lid = f"ol_{uuid.uuid4().hex[:6]}"
    return text_content(f"opened loop {lid}: {title}")


@tool(
    "close_open_loop",
    (
        "Close an open loop by id. Returns confirmation. "
        "USE WHEN: the user indicates they handled something ('texted luca', 'done with X'), "
        "and you've confirmed which open loop it resolves via list_open_loops first. "
        "DO NOT USE: without first reading the id from list_open_loops."
    ),
    {"id": str},
)
async def close_open_loop(args):
    lid = str(args.get("id", "")).strip() or "?"
    return text_content(f"closed loop {lid}.")


@tool(
    "schedule_reminder",
    (
        "Schedule a one-shot reminder. Returns confirmation with time. "
        "USE WHEN: the user wants a timed nudge ('remind me tomorrow at 9'). "
        "DO NOT USE: for open-ended commitments without a time (use track_open_loop)."
    ),
    {"when": str, "text": str},
)
async def schedule_reminder(args):
    when = str(args.get("when", "")).strip() or "unspecified"
    txt = str(args.get("text", "")).strip() or "(empty)"
    return text_content(f"scheduled '{txt}' for {when}.")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

from .tool_logic import send_burst_result  # noqa: E402
from .hooks import _CURRENT_TRACE, _fire_memory_hooks  # noqa: E402
from .langsmith_tracing import traceable  # noqa: E402


@tool(
    "send_burst",
    "TERMINATOR. Send 1-3 WhatsApp messages (<200 chars each, lowercase, no em dashes). "
    "tone: 'crisp' | 'direct' | 'warm'.",
    {"messages": list, "tone": str},
)
@traceable(name="donna.tool.send_burst", run_type="tool")
async def send_burst(args):
    result = await send_burst_result(args)
    _fire_memory_hooks(_CURRENT_TRACE.get(), args)
    return result


FAKE_DONNA_TOOLS = (
    recall_episodic,
    recall_graph,
    smart_recall,
    read_tracker,
    list_observations,
    list_open_loops,
    list_calendar,
    log_observation,
    track_open_loop,
    close_open_loop,
    schedule_reminder,
    send_burst,
)


FAKE_ALLOWED_TOOLS = tuple(
    f"mcp__donna__{name}"
    for name in (
        "recall_episodic",
        "recall_graph",
        "smart_recall",
        "read_tracker",
        "list_observations",
        "list_open_loops",
        "list_calendar",
        "log_observation",
        "track_open_loop",
        "close_open_loop",
        "schedule_reminder",
        "send_burst",
    )
)
