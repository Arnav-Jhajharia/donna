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
    "smart_recall",
    (
        "Adaptive recall across episodic, graph, and document memory. Returns the top "
        "mixed hits. "
        "USE WHEN: you want the best answer without picking a source (vague questions, "
        "'what did we talk about'). "
        "DO NOT USE: when the question is clearly source-specific — pass purpose to recall "
        "instead. Never call twice in one turn — use what you got."
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
    return text_content("\n".join(lines))


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
        "DO NOT USE: for past events (use recall) or to create events (no tool yet)."
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


async def _fake_attend_text(intent: str) -> str:
    aid = f"att_{uuid.uuid4().hex[:6]}"
    return f"attention created: '{intent or 'reminder'}' (attention_id={aid})"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

from .tool_logic import send_burst_result  # noqa: E402
from .hooks import _CURRENT_TRACE, _fire_memory_hooks  # noqa: E402
from .langsmith_tracing import traceable  # noqa: E402


@tool(
    "recall",
    "Fake affordance wrapper for recall. Returns canned memory, observations, loops, or brief-like context.",
    {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "purpose": {"type": "string"},
            "observation_type": {"type": "string"},
            "period": {"type": "string"},
            "limit": {"type": "integer"},
        },
    },
)
async def recall(args):
    purpose = str(args.get("purpose") or "auto").strip().lower()
    if purpose in {"observations", "tracker"} or args.get("observation_type") or args.get("period"):
        return await read_tracker({"name": args.get("observation_type") or "expense"})
    if purpose in {"open_loops", "loops"}:
        return await list_open_loops({})
    if purpose in {"situation_brief", "brief"}:
        return text_content(
            "this week: antler pitch pressure, deck polish, donna launch work. watch: luca, deck slide 4, sleep debt."
        )
    return await smart_recall({"message": args.get("query") or ""})


@tool(
    "remember",
    (
        "Fake affordance wrapper for private memory writes. Routes to canned "
        "observation/open-loop confirmations. Use only when the current user "
        "message introduced or confirmed the memory; do not re-save USER MODEL, "
        "SITUATION BRIEF, runtime context, or recall results."
    ),
    {
        "type": "object",
        "required": ["kind", "content"],
        "properties": {
            "kind": {"type": "string"},
            "content": {"type": "string"},
            "observation_type": {"type": "string"},
            "fields": {"type": "object"},
            "loop_id": {"type": "string"},
            "fact_key": {"type": "string"},
            "timezone": {"type": "string"},
            "confidence": {"type": "string"},
        },
    },
)
async def remember(args):
    kind = str(args.get("kind") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    if kind == "observation":
        return await log_observation(
            {
                "type": args.get("observation_type") or "note",
                "value": str(args.get("fields") or content),
                "note": content,
            }
        )
    if kind in {"open_loop", "commitment"}:
        return await track_open_loop({"title": content})
    if kind == "loop_closed":
        return await close_open_loop({"id": args.get("loop_id") or "ol_001"})
    if kind == "timezone":
        return text_content(f"remembered timezone: {args.get('timezone') or content}")
    return text_content(f"remembered {kind or 'note'}: {content}")


@tool(
    "attend",
    (
        "Fake affordance wrapper for the unified attention creation primitive. "
        "Mirrors the real `attend` tool: any timed reminder, recurring nudge, "
        "or standing watch. Returns a canned attention_id."
    ),
    {
        "type": "object",
        "required": ["intent"],
        "properties": {
            "intent": {"type": "string"},
            "origin": {"type": "string", "enum": ["user", "donna"]},
        },
    },
)
async def attend(args):
    intent = str(args.get("intent") or "").strip()
    return text_content(await _fake_attend_text(intent))


@tool(
    "list_attentions",
    "Fake affordance wrapper for listing pending attentions.",
    {"type": "object", "properties": {}},
)
async def list_attentions(args):
    return text_content("No attentions.")


@tool(
    "cancel_attention",
    "Fake affordance wrapper for cancelling an attention by id.",
    {
        "type": "object",
        "required": ["attention_id"],
        "properties": {"attention_id": {"type": "string"}},
    },
)
async def cancel_attention(args):
    aid = str(args.get("attention_id") or "").strip() or "?"
    return text_content(f"Cancelled attention_id={aid}.")


@tool(
    "snooze_attention",
    "Fake affordance wrapper for snoozing an attention by N minutes.",
    {
        "type": "object",
        "required": ["attention_id", "minutes"],
        "properties": {
            "attention_id": {"type": "string"},
            "minutes": {"type": "integer"},
        },
    },
)
async def snooze_attention(args):
    aid = str(args.get("attention_id") or "").strip() or "?"
    minutes = int(args.get("minutes") or 0)
    return text_content(f"snoozed attention_id={aid} by {minutes} min.")


@tool(
    "check_calendar",
    "Fake affordance wrapper for upcoming calendar context.",
    {
        "type": "object",
        "properties": {"purpose": {"type": "string"}, "within_days": {"type": "integer"}, "limit": {"type": "integer"}},
        "required": [],
    },
)
async def check_calendar(args):
    return await list_calendar({})


@tool(
    "image",
    (
        "Fake affordance wrapper for the image tool. Returns a deterministic "
        "placeholder media_id so smoke evals can exercise image turns without "
        "hitting fal.ai or Meta."
    ),
    {
        "type": "object",
        "required": ["intent", "caption"],
        "properties": {
            "intent": {"type": "string"},
            "caption": {"type": "string"},
        },
    },
)
async def image(args):
    intent = (args.get("intent") or "").strip() if isinstance(args, dict) else ""
    caption = (args.get("caption") or "").strip() if isinstance(args, dict) else ""
    if not intent or not caption:
        return text_content(
            "image unavailable: intent and caption are both required. go text."
        )
    fake_id = f"fake_media_{uuid.uuid4().hex[:8]}"
    return text_content(
        f"image ready: {fake_id}. use it in send_burst as an image item "
        f"with media_id={fake_id}, caption unchanged."
    )


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
    recall,
    remember,
    attend,
    list_attentions,
    cancel_attention,
    snooze_attention,
    check_calendar,
    image,
    send_burst,
)


FAKE_ALLOWED_TOOLS = tuple(
    f"mcp__donna__{name}"
    for name in (
        "recall",
        "remember",
        "attend",
        "list_attentions",
        "cancel_attention",
        "snooze_attention",
        "check_calendar",
        "image",
        "send_burst",
    )
)
