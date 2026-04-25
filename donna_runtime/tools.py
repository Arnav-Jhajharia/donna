from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from claude_agent_sdk import tool

from backend.memory.user_facts.schema import FactKey

logger = logging.getLogger(__name__)

_FACT_KEY_VALUES: tuple[str, ...] = tuple(k.value for k in FactKey)
_FACT_KEY_DESCRIPTION = (
    "Canonical fact key when kind is fact/preference. Must be one of: "
    + ", ".join(_FACT_KEY_VALUES)
    + ". Use preferred_name for what the user wants to be called."
)

from .hooks import (
    _CURRENT_TRACE,
    _CURRENT_USER_ID,
    _fire_memory_hooks,
    set_image_prompt_hash,
)
from .langsmith_tracing import traceable
from .tool_logic import (
    compose_image_prompt,
    read_tracker_result,
    recall_episodic_result,
    send_burst_result,
    text_content,
)


def _current_user_id() -> str | None:
    return _CURRENT_USER_ID.get()


def _tool_text(
    result: dict[str, Any],
    *,
    no_hits_text: str = "No hits.",
    degraded_text: str = "Memory unavailable.",
) -> dict[str, list[dict[str, str]]]:
    status = result.get("status")
    payload = result.get("payload")
    if status == "degraded":
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return text_content(f"{degraded_text}{f' {reason}' if reason else ''}")
    if status == "no_hits" or not payload:
        return text_content(no_hits_text)
    return text_content(_render_payload(payload))


_LIST_CAP = 10


def _render_payload(payload: Any, *, narrow_hint: str | None = None) -> str:
    if isinstance(payload, list):
        total = len(payload)
        lines: list[str] = []
        for item in payload[:_LIST_CAP]:
            if isinstance(item, dict):
                lines.append("- " + _render_dict_item(item))
            else:
                lines.append(f"- {item}")
        rendered = "\n".join(lines)
        if total > _LIST_CAP:
            hint = narrow_hint or "narrow with a more specific query, period, or purpose"
            rendered += f"\n(showing {_LIST_CAP} of {total} — {hint})"
        return rendered
    if isinstance(payload, dict):
        return json.dumps(payload, default=str, sort_keys=True)
    return str(payload)


def _render_dict_item(item: dict[str, Any]) -> str:
    for key in ("content", "fact", "rule", "title"):
        if item.get(key):
            prefix = f"{item.get('source')}: " if item.get("source") else ""
            return prefix + str(item[key])
    return json.dumps(item, default=str, sort_keys=True)


def _result_text(
    label: str,
    result: dict[str, Any],
    *,
    no_hits_text: str | None = None,
    degraded_text: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    status = result.get("status")
    payload = result.get("payload")
    if status == "ok":
        return text_content(f"{label}: {_render_payload(payload)}")
    if status == "no_hits":
        return text_content(no_hits_text or f"{label}: no hits.")
    reason = payload.get("reason") if isinstance(payload, dict) else None
    suffix = f" {reason}" if reason else ""
    return text_content((degraded_text or f"{label}: unavailable.") + suffix)


@tool(
    "recall_episodic",
    "Search episodic memory for past-conversation snippets not in the Living Profile. "
    "Returns up to 5 dated snippets. "
    "Do NOT use if the Living Profile already has the answer, for countable "
    "observations (use read_tracker), or for relational facts (use recall_graph).",
    {"query": str},
)
@traceable(name="donna.tool.recall_episodic", run_type="tool")
async def recall_episodic(args):
    return await recall_episodic_result(args)


@tool(
    "read_tracker",
    "Read-only tracker lookup by observation type (e.g. 'expense', 'mood'). "
    "Use period for local-time questions like today, this week, or last week. "
    "Returns JSON list of recent observations with local timestamps. "
    "Do NOT use for free-text memory recall or for non-countable events; "
    "use recall_episodic or smart_recall instead.",
    {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "period": {
                "type": "string",
                "description": "Optional local-time period: today, yesterday, this_week, or last_week.",
            },
        },
    },
)
@traceable(name="donna.tool.read_tracker", run_type="tool")
async def read_tracker(args):
    return await read_tracker_result(args)


@tool(
    "recall_graph",
    "Search the user's knowledge graph for relational facts (people, decisions, "
    "commitments). Returns up to 10 facts with timestamps. "
    "Do NOT use for countable observations (use read_tracker) or for "
    "free-text episodic snippets (use recall_episodic).",
    {"query": str},
)
@traceable(name="donna.tool.recall_graph", run_type="tool")
async def recall_graph(args):
    from backend.memory.tools.recall_graph import recall_graph as _recall_graph

    user_id = _current_user_id()
    query = str(args.get("query", "")).strip()
    if not user_id or not query:
        return text_content("No graph hits.")
    res = await _recall_graph(user_id=user_id, query=query, limit=10)
    return _tool_text(res, no_hits_text="No graph hits.", degraded_text="Graph unavailable.")


@tool(
    "smart_recall",
    "Adaptive recall across episodic, graph, and document memory. Use when you "
    "need the best-ranked hits without choosing a specific source. "
    "Do NOT use when the source is obvious (prefer the specific tool), "
    "when the Living Profile already answers the question, or after you "
    "already called a specific recall tool this turn — use what you got.",
    {"message": str},
)
@traceable(name="donna.tool.smart_recall", run_type="tool")
async def smart_recall(args):
    from backend.memory.tools.smart_recall import smart_recall as _smart_recall

    user_id = _current_user_id()
    message = str(args.get("message", "")).strip()
    if not user_id or not message:
        return text_content("No hits.")
    try:
        res = await _smart_recall(user_id=user_id, message=message, top_k=8)
    except Exception:
        logger.exception("smart_recall: pipeline failure")
        return text_content("Recall unavailable.")
    return _tool_text(res, no_hits_text="No hits.", degraded_text="Recall unavailable.")


@tool(
    "list_open_loops",
    "List active unresolved threads for this user. Use when deciding what the "
    "user may be forgetting or what needs follow-up. "
    "Do NOT use for calendar events (use list_calendar) or for historical "
    "context (use recall_episodic).",
    {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "limit": {"type": "integer"},
        },
    },
)
@traceable(name="donna.tool.list_open_loops", run_type="tool")
async def list_open_loops(args):
    from backend.memory.tools.list_open_loops import list_open_loops as _list_open_loops

    user_id = _current_user_id()
    if not user_id:
        return text_content("No open loops.")
    res = await _list_open_loops(
        user_id=user_id,
        status=str(args.get("status") or "active"),
        limit=int(args.get("limit") or 10),
    )
    return _tool_text(res, no_hits_text="No open loops.", degraded_text="Open loops unavailable.")


@tool(
    "list_calendar",
    "List upcoming calendar entries synced from the user's Google Calendar. "
    "Returns title, start/end in the user's local time, and location when set. "
    "Optional `within_days` (default horizon ~7) and `limit` (default 10). "
    "Use for schedule-aware replies: conflict checks, 'what's next', "
    "availability, context-aware timing ('8am meds while going out for lunch' "
    "-> check lunch time). Do NOT use for past events (use recall_episodic), "
    "untimed follow-ups (use list_open_loops), or when the user's question "
    "has no time dimension.",
    {
        "type": "object",
        "properties": {
            "within_days": {"type": "integer"},
            "limit": {"type": "integer"},
        },
    },
)
@traceable(name="donna.tool.list_calendar", run_type="tool")
async def list_calendar(args):
    from backend.memory.tools.list_calendar import list_calendar as _list_calendar

    user_id = _current_user_id()
    if not user_id:
        return text_content("No calendar entries.")
    res = await _list_calendar(
        user_id=user_id,
        within_days=int(args.get("within_days") or 7),
        limit=int(args.get("limit") or 10),
    )
    return _tool_text(res, no_hits_text="No calendar entries.", degraded_text="Calendar unavailable.")


@tool(
    "list_gmail_recent",
    "List recent gmail messages from the user's mailbox (read from local "
    "mirror; webhook-fed). Returns id, thread_id, from, subject, snippet, "
    "is_important, internal_date. Optional `within_hours` (default 24), "
    "`limit` (default 20), `important_only` (default false). Use when the "
    "user asks 'any new mail?', 'what came in today?', or 'has X emailed?'. "
    "Do NOT use for a specific thread by sender or subject (use "
    "read_gmail_thread), or when the [INTEGRATIONS] block shows google_gmail "
    "as not_connected.",
    {
        "type": "object",
        "properties": {
            "within_hours": {"type": "integer"},
            "limit": {"type": "integer"},
            "important_only": {"type": "boolean"},
        },
    },
)
@traceable(name="donna.tool.list_gmail_recent", run_type="tool")
async def list_gmail_recent(args):
    from backend.memory.tools.list_gmail_recent import (
        list_gmail_recent as _list_gmail_recent,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("No recent mail.")
    res = await _list_gmail_recent(
        user_id=user_id,
        within_hours=int(args.get("within_hours") or 24),
        limit=int(args.get("limit") or 20),
        important_only=bool(args.get("important_only") or False),
    )
    return _tool_text(res, no_hits_text="No recent mail.", degraded_text="Gmail unavailable.")


@tool(
    "read_gmail_thread",
    "Fetch all messages in one gmail thread with full bodies. If a body was "
    "filtered at ingest (label policy stored metadata only), this tool "
    "lazy-fetches it from Composio and persists it. Use when the user asks "
    "about a specific thread you've already shown them, or when you need "
    "full content to compose a reply or summarize a conversation. Do NOT "
    "use for 'what's new in my inbox?' (use list_gmail_recent), or when "
    "the [INTEGRATIONS] block shows google_gmail as not_connected.",
    {
        "type": "object",
        "required": ["thread_id"],
        "properties": {
            "thread_id": {"type": "string"},
        },
    },
)
@traceable(name="donna.tool.read_gmail_thread", run_type="tool")
async def read_gmail_thread(args):
    from backend.memory.tools.read_gmail_thread import (
        read_gmail_thread as _read_gmail_thread,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot read thread: no user_id.")
    thread_id = str(args.get("thread_id") or "").strip()
    if not thread_id:
        return text_content("Cannot read thread: thread_id is required.")
    res = await _read_gmail_thread(user_id=user_id, thread_id=thread_id)
    return _tool_text(res, no_hits_text="Thread not found.", degraded_text="Gmail unavailable.")


@tool(
    "log_observation",
    "Record a countable user event. `type` is the category (expense, meal, mood, "
    "sleep, habit, exercise, symptom). `fields` is the numeric/structured payload "
    "('amount_usd': 6 for an expense, 'hours': 7 for sleep, 'score': 4 for mood 1-5). "
    "Include `event_time` as an ISO timestamp when the event happened earlier than "
    "this message ('coffee was 6 bucks this morning' -> event_time = this morning). "
    "Do NOT use for feelings, intentions, decisions, commitments, or vague statements "
    "('i feel tired', 'thinking about quitting') — those are open_loops or memory, "
    "not observations. Do NOT invent a number the user did not state. Do NOT use for "
    "the same event twice within a turn.",
    {
        "type": "object",
        "required": ["type", "fields"],
        "properties": {
            "type": {"type": "string"},
            "fields": {"type": "object"},
            "tags": {"type": "object"},
            "raw": {"type": "string"},
            "event_time": {
                "type": "string",
                "description": "Optional ISO timestamp for when the event happened.",
            },
            "confidence": {"type": "number"},
        },
    },
)
@traceable(name="donna.tool.log_observation", run_type="tool")
async def log_observation(args):
    from backend.memory.tools.log_observation import log_observation as _log_observation

    user_id = _current_user_id()
    obs_type = str(args.get("type") or "").strip()
    fields = args.get("fields") if isinstance(args.get("fields"), dict) else {}
    if not user_id or not obs_type or not fields:
        return text_content("Observation not logged.")
    res = await _log_observation(
        user_id=user_id,
        type=obs_type,
        fields=fields,
        tags=args.get("tags") if isinstance(args.get("tags"), dict) else {},
        raw=str(args.get("raw") or ""),
        event_time=str(args.get("event_time") or ""),
        confidence=float(args.get("confidence") or 1.0),
    )
    return _tool_text(res, no_hits_text="Observation not logged.", degraded_text="Observation unavailable.")


@tool(
    "track_open_loop",
    "Record an unresolved thread or commitment. Use when the user leaves a "
    "follow-up, decision, or obligation hanging. "
    "Do NOT use for timed reminders (use schedule_reminder) or for completed "
    "facts (use log_observation).",
    {
        "type": "object",
        "required": ["content"],
        "properties": {
            "content": {"type": "string"},
            "source_message": {"type": "string"},
        },
    },
)
@traceable(name="donna.tool.track_open_loop", run_type="tool")
async def track_open_loop(args):
    from backend.memory.tools.track_open_loop import track_open_loop as _track_open_loop

    user_id = _current_user_id()
    content = str(args.get("content") or "").strip()
    if not user_id or not content:
        return text_content("Open loop not tracked.")
    res = await _track_open_loop(
        user_id=user_id,
        content=content,
        source_message=str(args.get("source_message") or ""),
    )
    return _tool_text(res, no_hits_text="Open loop not tracked.", degraded_text="Open loops unavailable.")


@tool(
    "close_open_loop",
    "Mark a prior open loop resolved. Use a loop id from list_open_loops. "
    "Do NOT use without a loop_id or on a loop the user has not confirmed resolved.",
    {
        "type": "object",
        "required": ["loop_id"],
        "properties": {"loop_id": {"type": "string"}},
    },
)
@traceable(name="donna.tool.close_open_loop", run_type="tool")
async def close_open_loop(args):
    from backend.memory.tools.close_open_loop import close_open_loop as _close_open_loop

    user_id = _current_user_id()
    loop_id = str(args.get("loop_id") or "").strip()
    if not user_id or not loop_id:
        return text_content("Open loop not closed.")
    res = await _close_open_loop(user_id=user_id, loop_id=loop_id)
    return _tool_text(res, no_hits_text="Open loop not found.", degraded_text="Open loops unavailable.")


@tool(
    "set_timezone",
    "Set the user's timezone. `timezone` MUST be a valid IANA string "
    "('Asia/Singapore', 'America/New_York', 'Europe/London') — never an "
    "abbreviation ('PST', 'IST') or UTC offset ('+05:30'). Use only when the "
    "user explicitly confirms or corrects their timezone. Do NOT use on a "
    "passing location reference ('i'm in tokyo this week' ≠ timezone change), "
    "on a guess, or when the timezone check in runtime context already shows "
    "confirmed=true.",
    {
        "type": "object",
        "required": ["timezone"],
        "properties": {
            "timezone": {"type": "string"},
            "source": {"type": "string", "description": "Optional provenance label (default: user_correction)."},
        },
    },
)
@traceable(name="donna.tool.set_timezone", run_type="tool")
async def set_timezone(args):
    from backend.memory.tools.set_timezone import set_timezone as _set_timezone

    user_id = _current_user_id()
    tz = str(args.get("timezone") or "").strip()
    if not user_id:
        return text_content(
            "Timezone not updated: no user_id in scope. Runtime bug — report it."
        )
    if not tz:
        return text_content(
            "Timezone not updated: 'timezone' is required. Pass an IANA name like "
            "'Asia/Singapore', 'America/New_York', or 'Europe/London' — never an "
            "abbreviation ('PST', 'IST') or UTC offset ('+05:30')."
        )
    res = await _set_timezone(
        user_id=user_id,
        timezone=tz,
        source=str(args.get("source") or "user_correction"),
    )
    return _tool_text(res, no_hits_text="Timezone not updated.", degraded_text="Timezone unavailable.")


@tool(
    "connect_integration",
    "Generate a connect link for an external provider (currently: google, "
    "covering calendar and gmail). Use when the [INTEGRATIONS] context block "
    "shows the integration as not_connected and the user asks for something "
    "requiring it, or asks to connect explicitly. Do NOT use when the "
    "integration is already connected, when status is 'pending' (a link is "
    "already in flight — do not nag), or when the user is mid-task and a "
    "connect prompt would derail them. Returns a one-line consent message "
    "containing the URL — forward it verbatim.",
    {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "enum": ["google"]},
            "products": {
                "type": "array",
                "items": {"type": "string", "enum": ["calendar", "gmail"]},
                "minItems": 1,
            },
        },
        "required": ["provider", "products"],
    },
)
@traceable(name="donna.tool.connect_integration", run_type="tool")
async def connect_integration(args):
    from backend.memory.tools.connect_integration import (
        connect_integration as _connect,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot connect: no user_id in scope.")
    provider = str(args.get("provider") or "google").strip()
    raw_products = args.get("products") or ["calendar", "gmail"]
    if not isinstance(raw_products, list):
        raw_products = [raw_products]
    products = [str(p).strip() for p in raw_products if str(p).strip()]
    if not products:
        return text_content("Cannot connect: 'products' is required.")

    res = await _connect(user_id=user_id, provider=provider, products=products)
    status = res.get("status")
    if status == "already_connected":
        return text_content("already connected.")
    if status == "error":
        return text_content(f"connect failed: {res.get('message') or 'unknown'}")
    return text_content(res.get("message") or f"tap: {res.get('url')}")


@tool(
    "schedule_reminder",
    "Schedule a one-shot reminder to be delivered to the user at a specific "
    "time. `text` is what the reminder will say (write it as Donna, not as the "
    "user). Provide EITHER `fire_at` (ISO timestamp, resolve ambiguous times "
    "via resolve_time_expression first) OR `in_minutes` (relative offset) — "
    "not both. Use when the user explicitly asks to be reminded at a time "
    "('remind me at 6pm', 'text me in an hour', 'ping me tomorrow morning'). "
    "Do NOT use for open-ended follow-ups with no clock time ('remind me about "
    "sarah', 'don't let me forget the deck') — those are track_open_loop. Do "
    "NOT use for recurring reminders (not supported — one-shot only). Do NOT "
    "invent a time the user did not give.",
    {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "fire_at": {"type": "string", "description": "Optional ISO timestamp (use offset when known)."},
            "in_minutes": {"type": "integer", "description": "Optional relative delay in minutes (alternative to fire_at)."},
        },
    },
)
@traceable(name="donna.tool.schedule_reminder", run_type="tool")
async def schedule_reminder(args):
    from backend.memory.tools.schedule_reminder import schedule_reminder as _schedule_reminder

    user_id = _current_user_id()
    text = str(args.get("text") or "").strip()
    if not user_id or not text:
        return text_content("Reminder not scheduled.")
    res = await _schedule_reminder(
        user_id=user_id,
        text=text,
        fire_at=str(args.get("fire_at") or "") or None,
        in_minutes=(int(args["in_minutes"]) if args.get("in_minutes") is not None else None),
        origin="user",
    )
    return _tool_text(res, no_hits_text="Reminder not scheduled.", degraded_text="Scheduling unavailable.")


@tool(
    "resolve_time_expression",
    (
        "Resolve a natural-language time expression ('last tuesday', "
        "'3 hours ago', 'tomorrow at 6pm') to a concrete UTC ISO timestamp "
        "anchored in the user's timezone. Use before filtering bi-temporal "
        "facts by t_valid or before scheduling. "
        "Do NOT use for ISO timestamps the user already gave, for vague "
        "durations like 'a few days' (ask the user), or when no time "
        "dimension is present."
    ),
    {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {"type": "string"},
            "now": {
                "type": "string",
                "description": "Optional ISO anchor for 'now' (testing only).",
            },
        },
    },
)
@traceable(name="donna.tool.resolve_time_expression", run_type="tool")
async def resolve_time_expression(args):
    from backend.memory.tools.resolve_time_expression import (
        resolve_time_expression as _resolve,
    )

    user_id = _current_user_id()
    expression = str(args.get("expression") or "").strip()
    if not user_id or not expression:
        return text_content("Could not resolve time expression.")
    res = await _resolve(
        user_id=user_id,
        expression=expression,
        now=args.get("now") or None,
    )
    return _tool_text(
        res,
        no_hits_text="Could not resolve time expression.",
        degraded_text="Could not resolve time expression.",
    )


@tool(
    "read_situation_brief",
    (
        "Read the raw stored situation brief (last/this/next week model), "
        "including generated_at timestamp and evidence counts. Use to verify "
        "freshness or cite evidence counts. "
        "Do NOT use for normal 'what's my week' questions — the rendered "
        "brief is already in the wrapped user prompt."
    ),
    {
        "type": "object",
        "properties": {},
        "required": [],
    },
)
@traceable(name="donna.tool.read_situation_brief", run_type="tool")
async def read_situation_brief(args):
    from backend.memory.tools.read_situation_brief import (
        read_situation_brief as _read,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("No situation brief.")
    res = await _read(user_id=user_id)
    return _tool_text(
        res,
        no_hits_text="No situation brief.",
        degraded_text="Situation brief unavailable.",
    )


@tool(
    "recall",
    (
        "Recall context for Donna. Use when the reply depends on prior memory, "
        "tracked observations, unresolved loops, or the user's current situation. "
        "This is an affordance wrapper: ask for the outcome, not the backend. "
        "Use purpose only as an escape hatch when Donna explicitly needs to force "
        "observations, open loops, or the stored situation brief. "
        "Do NOT use when the Living Profile, SITUATION BRIEF, or runtime context "
        "already answers the question — those are in the cached prompt. "
        "Do NOT call twice in the same turn — use what the first call returned. "
        "Do NOT use for calendar lookups (use check_calendar)."
    ),
    {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "purpose": {
                "type": "string",
                "description": "auto, observations, open_loops, or situation_brief.",
            },
            "observation_type": {
                "type": "string",
                "description": "Optional tracker category such as expense, mood, sleep.",
            },
            "period": {
                "type": "string",
                "description": "Optional local period: today, yesterday, this_week, last_week.",
            },
            "limit": {"type": "integer"},
        },
    },
)
@traceable(name="donna.tool.recall", run_type="tool")
async def recall(args):
    user_id = _current_user_id()
    query = str(args.get("query") or "").strip()
    if not user_id:
        return text_content(
            "Recall unavailable: no user_id in scope. Runtime bug — report it."
        )
    if not query:
        return text_content(
            "Recall unavailable: 'query' is required. Pass a natural-language "
            "question or topic, e.g. 'what's pending with priya' or "
            "'my expenses this week'. To force a specific source, also pass "
            "purpose='observations' | 'open_loops' | 'situation_brief'."
        )

    purpose = str(args.get("purpose") or "auto").strip().lower()
    limit = int(args.get("limit") or 8)

    if purpose in {"observations", "tracker"} or args.get("observation_type") or args.get("period"):
        from backend.memory.tools.list_observations import list_observations

        res = await list_observations(
            user_id=user_id,
            type=(str(args.get("observation_type") or "").strip() or None),
            period=(str(args.get("period") or "").strip() or None),
            limit=limit,
        )
        return _result_text("observations", res, no_hits_text="No observations.")

    if purpose in {"open_loops", "loops"}:
        from backend.memory.tools.list_open_loops import list_open_loops

        res = await list_open_loops(user_id=user_id, status="active", limit=limit)
        return _result_text("open loops", res, no_hits_text="No open loops.")

    if purpose in {"situation_brief", "brief"}:
        from backend.memory.tools.read_situation_brief import read_situation_brief

        res = await read_situation_brief(user_id=user_id)
        return _result_text("situation brief", res, no_hits_text="No situation brief.")

    from backend.memory.tools.smart_recall import smart_recall as _smart_recall

    try:
        res = await _smart_recall(user_id=user_id, message=query, top_k=limit)
    except Exception:
        logger.exception("recall wrapper failed")
        return text_content("Recall unavailable.")
    return _tool_text(res, no_hits_text="No hits.", degraded_text="Recall unavailable.")


@tool(
    "remember",
    (
        "Record a user-stated observation, open thread, thread resolution, or "
        "timezone into memory. This wrapper routes to the right backend. Bias "
        "toward using it when the current user message gives information Donna "
        "should hold onto. "
        "Profile facts (name, city, profession, age, etc.) are handled "
        "automatically by a pre-turn detector and the post-turn extractor — "
        "do NOT call this with kind='fact' or kind='preference'. Those kinds "
        "are removed. "
        "Do NOT call this to re-save things that only came from USER MODEL, "
        "SITUATION BRIEF, runtime context, or a recall result. "
        "Do NOT invent values the user did not state (no fabricated amounts, "
        "timezones). "
        "Do NOT use for timed reminders (use schedule) or for things better "
        "surfaced as a dashboard attention (use watch). "
        "Do NOT call twice for the same observation/loop/timezone within one turn."
    ),
    {
        "type": "object",
        "required": ["kind", "content"],
        "properties": {
            "kind": {
                "type": "string",
                "description": "observation, open_loop, commitment, loop_closed, or timezone.",
            },
            "content": {"type": "string"},
            "observation_type": {"type": "string"},
            "fields": {"type": "object"},
            "tags": {"type": "object"},
            "event_time": {"type": "string"},
            "loop_id": {"type": "string"},
            "timezone": {"type": "string"},
            "confidence": {"type": "string", "description": "low, medium, or high."},
        },
    },
)
@traceable(name="donna.tool.remember", run_type="tool")
async def remember(args):
    user_id = _current_user_id()
    kind = str(args.get("kind") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    if not user_id:
        return text_content(
            "Memory not recorded: no user_id in scope. This is a runtime bug, "
            "not a tool-call error — report it and move on."
        )
    if not kind:
        return text_content(
            "Memory not recorded: 'kind' is required. Valid kinds: "
            + ", ".join(["observation", "open_loop", "commitment", "loop_closed",
                         "timezone"])
            + "."
        )
    if kind in {"fact", "preference"}:
        return text_content(
            "Memory not recorded: kind='fact' and kind='preference' have been "
            "removed from remember. Profile facts (name, city, profession, etc.) "
            "are written automatically by the pre-turn detector and post-turn "
            "extractor when the user states them. Drop the tool call; just reply."
        )
    if not content:
        return text_content(
            f"Memory not recorded: 'content' is required (got empty string). "
            f"For kind={kind!r}, pass the user-stated fact/commitment/value."
        )

    if kind == "observation":
        from backend.memory.tools.log_observation import log_observation as _log_observation

        obs_type = str(args.get("observation_type") or "").strip()
        fields = args.get("fields") if isinstance(args.get("fields"), dict) else {}
        if not obs_type:
            return text_content(
                "Observation not recorded: 'observation_type' is required. "
                "Common types: expense, meal, mood, sleep, habit, exercise, symptom. "
                "Example: observation_type='expense', fields={'amount_usd': 6}."
            )
        if not fields:
            return text_content(
                f"Observation not recorded: 'fields' is required and must be a non-empty object. "
                f"For observation_type={obs_type!r}, pass the numeric/structured payload "
                f"(e.g. {{'amount_usd': 6}} for expense, {{'hours': 7}} for sleep, {{'score': 4}} for mood)."
            )
        res = await _log_observation(
            user_id=user_id,
            type=obs_type,
            fields=fields,
            tags=args.get("tags") if isinstance(args.get("tags"), dict) else {},
            raw=content,
            event_time=str(args.get("event_time") or ""),
            confidence=_numeric_confidence(args.get("confidence")),
        )
        return _result_text("remembered observation", res, no_hits_text="Observation not recorded.")

    if kind in {"open_loop", "commitment"}:
        from backend.memory.tools.track_open_loop import track_open_loop as _track_open_loop

        res = await _track_open_loop(user_id=user_id, content=content, source_message=content)
        return _result_text("remembered open loop", res, no_hits_text="Open loop not recorded.")

    if kind == "loop_closed":
        from backend.memory.tools.close_open_loop import close_open_loop as _close_open_loop

        loop_id = str(args.get("loop_id") or "").strip()
        if not loop_id:
            return text_content(
                "Open loop not closed: 'loop_id' is required. "
                "Get it by calling recall(purpose='open_loops') first, then pass the "
                "id from the matching loop."
            )
        res = await _close_open_loop(user_id=user_id, loop_id=loop_id)
        return _result_text("closed open loop", res, no_hits_text="Open loop not found.")

    if kind == "timezone":
        from backend.memory.tools.set_timezone import set_timezone as _set_timezone

        tz = str(args.get("timezone") or content).strip()
        res = await _set_timezone(user_id=user_id, timezone=tz, source="user_correction")
        return _result_text("remembered timezone", res, no_hits_text="Timezone not updated.")

    return text_content(
        f"Memory not recorded: unsupported kind {kind!r}. "
        f"Valid kinds: observation, open_loop, commitment, loop_closed, timezone."
    )


def _numeric_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    return {"low": 0.4, "medium": 0.7, "high": 1.0}.get(text, 1.0)


def _fact_confidence(value: Any):
    from backend.memory.user_facts.schema import Confidence

    text = str(value or "medium").strip().lower()
    if text in {"low", "medium", "high"}:
        return Confidence(text)
    return Confidence.MEDIUM


@tool(
    "schedule",
    (
        "Schedule a one-shot future message/reminder to the user. Use when the "
        "user gives a time or asks Donna to ping/remind/text later. Accepts "
        "natural language in `when`; the wrapper resolves it before writing. "
        "Do NOT use for open-ended follow-ups with no clock time — those are "
        "remember(kind='open_loop'). "
        "Do NOT invent a time the user did not give. Ask them instead. "
        "Do NOT use for recurring reminders — one-shot only. "
        "Do NOT use for past events (memory, not scheduling)."
    ),
    {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "when": {"type": "string", "description": "Natural time, e.g. tomorrow morning."},
            "fire_at": {"type": "string", "description": "Optional ISO timestamp."},
            "in_minutes": {"type": "integer"},
        },
    },
)
@traceable(name="donna.tool.schedule", run_type="tool")
async def schedule(args):
    from backend.memory.tools.schedule_reminder import schedule_reminder as _schedule_reminder

    user_id = _current_user_id()
    text = str(args.get("text") or "").strip()
    if not user_id:
        return text_content(
            "Reminder not scheduled: no user_id in scope. Runtime bug — report it."
        )
    if not text:
        return text_content(
            "Reminder not scheduled: 'text' is required. Write what Donna should say "
            "to the user at fire time, in Donna's voice (not quoting the user)."
        )

    fire_at = str(args.get("fire_at") or "").strip() or None
    in_minutes = int(args["in_minutes"]) if args.get("in_minutes") is not None else None
    when = str(args.get("when") or "").strip()

    if not fire_at and in_minutes is None and not when:
        return text_content(
            "Reminder not scheduled: need one of fire_at (ISO timestamp), "
            "in_minutes (integer), or when (natural language like 'tomorrow at 6pm'). "
            "Do not invent a time — if the user did not give one, ask them."
        )

    if not fire_at and in_minutes is None and when:
        from backend.memory.tools.resolve_time_expression import resolve_time_expression as _resolve

        resolved = await _resolve(user_id=user_id, expression=when)
        if resolved.get("status") != "ok" or not isinstance(resolved.get("payload"), dict):
            reason = (
                resolved.get("payload", {}).get("reason")
                if isinstance(resolved.get("payload"), dict) else None
            )
            hint = (
                "Use fire_at with an ISO timestamp, or in_minutes with an integer. "
                "For ambiguous expressions ('a few days'), ask the user."
            )
            return text_content(
                f"Reminder not scheduled: could not resolve when={when!r}"
                f"{f' ({reason})' if reason else ''}. {hint}"
            )
        fire_at = str(resolved["payload"].get("at") or "").strip() or None

    res = await _schedule_reminder(
        user_id=user_id,
        text=text,
        fire_at=fire_at,
        in_minutes=in_minutes,
        origin="user",
    )
    return _result_text("scheduled", res, no_hits_text="Reminder not scheduled.")


@tool(
    "check_calendar",
    (
        "Check upcoming calendar context. Use for availability, conflicts, "
        "what is next, or timing-aware prep. Returns title, start/end in the "
        "user's local time, and location when set. "
        "Do NOT use for past events (use recall with a time-scoped query). "
        "Do NOT use for untimed follow-ups (use recall with purpose='open_loops'). "
        "Do NOT use when the user's question has no time dimension."
    ),
    {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"},
            "within_days": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": [],
    },
)
@traceable(name="donna.tool.check_calendar", run_type="tool")
async def check_calendar(args):
    from backend.memory.tools.list_calendar import list_calendar as _list_calendar

    user_id = _current_user_id()
    if not user_id:
        return text_content("No calendar entries.")
    res = await _list_calendar(
        user_id=user_id,
        within_days=int(args.get("within_days") or 7),
        limit=int(args.get("limit") or 10),
    )
    return _result_text("calendar", res, no_hits_text="No calendar entries.")


@tool(
    "watch",
    (
        "Create a standing attention for Donna to watch, track, brief, prep, "
        "or remind over time. Use when the user explicitly asks Donna to keep "
        "an eye on something, or when the user accepts a specific offer to "
        "watch it. "
        "Do NOT use on a passing interest reference ('i follow tech news' is "
        "not a watch request). "
        "Do NOT use when the user did not explicitly ask or accept. "
        "Do NOT use for a one-time timed reminder (use schedule) or an "
        "in-flight commitment (use remember with kind='open_loop')."
    ),
    {
        "type": "object",
        "required": ["intent"],
        "properties": {
            "intent": {
                "type": "string",
                "description": "Natural instruction, e.g. keep an eye on Poke launch updates.",
            },
            "auto_live": {
                "type": "boolean",
                "description": "True when user explicitly asked or accepted.",
            },
        },
    },
)
@traceable(name="donna.tool.watch", run_type="tool")
async def watch(args):
    user_id = _current_user_id()
    intent = str(args.get("intent") or "").strip()
    if not user_id:
        return text_content(
            "Watch not created: no user_id in scope. Runtime bug — report it and move on."
        )
    if not intent:
        return text_content(
            "Watch not created: 'intent' is required. Pass a natural instruction "
            "describing what Donna should keep an eye on, e.g. "
            "intent='keep an eye on the Poke launch updates'."
        )
    try:
        from donna.attention.tools import create_attention

        result = await create_attention(
            intent,
            user_id=user_id,
            auto_live=bool(args.get("auto_live", True)),
        )
    except Exception as exc:
        logger.exception("watch wrapper failed")
        return text_content(
            f"Watch not created: {type(exc).__name__}. "
            f"The attention backend may be unavailable — do not retry this turn."
        )
    title = result.attention.spec.title
    status = result.attention.status.value
    card = result.attention.spec.card.value
    return text_content(f"watch created: '{title}' ({card}, status={status})")


@tool(
    "image",
    (
        "Generate a warm hand-drawn illustration and return a handle for "
        "send_burst. Takes intent (one sentence of what the picture should "
        "say) and caption (what Donna will say under it, in her voice). The "
        "tool composes the image prompt from the user's facts; Donna does "
        "not write image prompts. Returns a media_id to thread into "
        "send_burst as an image item. "
        "WHEN TO USE: any time the user explicitly asks for an image, "
        "picture, drawing, or illustration of anything. Examples: 'send me "
        "an image of a banana', 'draw me a sunset', 'make a picture of x', "
        "'show me y'. The user asking IS the trigger. Do NOT refuse, do NOT "
        "second-guess, do NOT lecture about when you draw. Just call the "
        "tool. Also use proactively when a milestone or closed loop earns a "
        "picture (rare). "
        "WHEN NOT TO USE: photorealism of the user or any real person by "
        "name (hard rail), or for diagrams, receipts, or data tables (those "
        "are text). "
        "Hard rails the tool enforces in addition: one image per turn, "
        "ever. A 6h cooldown and a 3/week cap are enforced by the "
        "PreToolUse hook — expect a deny string when you overreach and "
        "fall through to text. On any failure (provider down, safety "
        "reject, cap hit), the return string tells you to skip the image "
        "and reply in text."
    ),
    {
        "type": "object",
        "required": ["intent", "caption"],
        "properties": {
            "intent": {
                "type": "string",
                "description": "One short sentence of what the picture should say.",
            },
            "caption": {
                "type": "string",
                "description": "The WhatsApp caption under the image, in Donna's voice.",
            },
        },
    },
)
@traceable(name="donna.tool.image", run_type="tool")
async def image(args):
    from .image_client import (
        ImageProviderError,
        ImageSafetyError,
        ImageUploadError,
        generate_and_upload,
    )

    user_id = _current_user_id()
    intent = (args.get("intent") or "").strip() if isinstance(args, dict) else ""
    caption = (args.get("caption") or "").strip() if isinstance(args, dict) else ""

    if not intent or not caption:
        return text_content(
            "image unavailable: intent and caption are both required. go text."
        )
    if not user_id:
        return text_content(
            "image unavailable: runtime user scope missing. go text."
        )

    try:
        composed_prompt = await compose_image_prompt(user_id, intent)
    except ValueError:
        return text_content("image unavailable: intent invalid. go text.")

    prompt_hash = hashlib.sha256(composed_prompt.encode("utf-8")).hexdigest()
    set_image_prompt_hash(prompt_hash)

    from delivery.whatsapp import WhatsAppChannel

    wa = WhatsAppChannel()

    try:
        result = await generate_and_upload(composed_prompt, wa)
    except ImageSafetyError as e:
        logger.info("image.safety_reject: %s", e)
        return text_content(
            "image rejected by safety filter. rewrite intent without the "
            "flagged element, or go text."
        )
    except ImageUploadError as e:
        logger.warning("image.upload_failed: %s", e)
        return text_content(
            "image unavailable: whatsapp media upload failed. skip the image, "
            "reply with text."
        )
    except ImageProviderError as e:
        logger.warning("image.provider_failed: %s", e)
        return text_content(
            "image unavailable: provider timeout. skip the image, reply with text."
        )
    except Exception:
        logger.exception("image tool unexpected failure")
        return text_content("image unavailable: unexpected failure. go text.")

    return text_content(
        f"image ready: {result.media_id}. use it in send_burst as an image "
        f"item with media_id={result.media_id}, caption unchanged."
    )


def _render_web_hits(hits: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for hit in hits:
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        snippet = str(hit.get("snippet") or "").strip()
        head = f"- {title} ({url})" if title else f"- {url}"
        if snippet:
            head += f" — {snippet}"
        lines.append(head)
    return "\n".join(lines)


def _render_agentic_answer(payload: dict[str, Any]) -> str:
    answer = str(payload.get("answer") or "").strip()
    sources = payload.get("sources") or []
    lines: list[str] = []
    if answer:
        lines.append(f"answer: {answer}")
    if sources:
        lines.append("sources:")
        for src in sources:
            title = str(src.get("title") or "").strip()
            url = str(src.get("url") or "").strip()
            if not url:
                continue
            lines.append(f"- {title} ({url})" if title else f"- {url}")
    return "\n".join(lines) if lines else "no web answer."


@tool(
    "web_search",
    (
        "Single-shot external web search. Returns 3-5 hits as "
        "'- title (url) — snippet' lines. "
        "Use for a fresh factual lookup Donna cannot know from memory: "
        "current events, prices, openings, definitions, references, "
        "people or companies the user just mentioned by name. "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use for facts already in the situation brief or chat. "
        "Do NOT use for comparison or synthesis across multiple sources "
        "(use agentic_web_search). "
        "Do NOT use for self-harm, medical emergency, or sensitive topics "
        "where safety floors apply. "
        "Do NOT chain multiple web_search calls in one turn, use "
        "agentic_web_search instead. "
        "The result is raw material, not a reply. Read it, pick the one "
        "thing that answers the question, synthesize in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Short search phrase. Plain words, not a question.",
            },
            "max_results": {
                "type": "integer",
                "description": "How many hits to return (1-10, default 5).",
            },
            "recency": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": (
                    "Optional recency filter when the answer depends on "
                    "freshness (news, scores, price). Omit otherwise."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.web_search", run_type="tool")
async def web_search(args):
    from backend.web.search import search_web as _search_web

    query = str(args.get("query") or "").strip() if isinstance(args, dict) else ""
    if not query:
        return text_content("web_search: query is required.")
    max_results = args.get("max_results") or 5
    recency = args.get("recency") if isinstance(args, dict) else None
    try:
        res = await _search_web(
            query,
            max_results=int(max_results),
            recency=recency if isinstance(recency, str) else None,
        )
    except Exception:
        logger.exception("web_search: unexpected failure")
        return text_content("web_search unavailable.")
    status = res.get("status")
    if status == "degraded":
        reason = (
            res.get("payload", {}).get("reason")
            if isinstance(res.get("payload"), dict)
            else ""
        )
        suffix = f" {reason}" if reason else ""
        return text_content(f"web_search unavailable.{suffix}")
    if status == "no_hits" or not res.get("payload"):
        return text_content("web_search: no hits.")
    return text_content(_render_web_hits(res["payload"]))


@tool(
    "agentic_web_search",
    (
        "Deeper multi-source web research. The provider reads several pages "
        "and returns a synthesized answer plus up to 5 supporting URLs. "
        "Use for comparison, synthesis, or 'current state of X' questions "
        "where one snippet will not cut it. Examples: "
        "'compare Poke and Limitless today', 'what are people saying about "
        "the openai sora pricing change', 'state of antler SG batch 13 "
        "companies'. "
        "Do NOT use for single-fact lookups (use web_search, cheaper). "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use speculatively when no external source helps. "
        "Do NOT use after web_search already gave a clear answer this turn. "
        "Call once per turn. The answer is raw material, not a reply — "
        "read it, pick the beat that matters, speak in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Specific research question in plain words. Include "
                    "comparison targets or scope if relevant."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "How many supporting sources to request (1-10, default 5).",
            },
        },
    },
)
@traceable(name="donna.tool.agentic_web_search", run_type="tool")
async def agentic_web_search(args):
    from backend.web.search import agentic_search as _agentic_search

    question = str(args.get("question") or "").strip() if isinstance(args, dict) else ""
    if not question:
        return text_content("agentic_web_search: question is required.")
    max_results = args.get("max_results") or 5
    try:
        res = await _agentic_search(question, max_results=int(max_results))
    except Exception:
        logger.exception("agentic_web_search: unexpected failure")
        return text_content("agentic_web_search unavailable.")
    status = res.get("status")
    if status == "degraded":
        reason = (
            res.get("payload", {}).get("reason")
            if isinstance(res.get("payload"), dict)
            else ""
        )
        suffix = f" {reason}" if reason else ""
        return text_content(f"agentic_web_search unavailable.{suffix}")
    if status == "no_hits" or not res.get("payload"):
        return text_content("agentic_web_search: no hits.")
    return text_content(_render_agentic_answer(res["payload"]))


def _render_research_answer(
    answer: str,
    sources: list[Any],
    *,
    confidence: float,
    dissent: str | None,
    variant: str,
) -> str:
    lines: list[str] = []
    if answer:
        lines.append(f"answer ({variant}, confidence={confidence:.2f}): {answer}")
    if dissent:
        lines.append(f"dissent: {dissent}")
    if sources:
        lines.append("sources:")
        for src in sources[:5]:
            title = (getattr(src, "title", "") or "").strip()
            url = (getattr(src, "url", "") or "").strip()
            if not url:
                continue
            lines.append(f"- {title} ({url})" if title else f"- {url}")
    return "\n".join(lines) if lines else "no web answer."


@tool(
    "research",
    (
        "Deep multi-stage web research. Runs our own pipeline: query "
        "expansion via Haiku, parallel Exa neural + keyword search, URL "
        "dedup + RRF, optional Cohere rerank, and a two-prompt synthesis "
        "(strict facts vs weak signals ok) with a judge. Returns one "
        "synthesized answer, a confidence score, an optional dissent line, "
        "and up to 5 cited sources. "
        "Use for questions that need real synthesis across sources: "
        "'how has X evolved', 'what are the tradeoffs between A and B', "
        "'what's the current state of Y', deep comparisons, reading the "
        "room on a topic the user just brought up. "
        "Do NOT use for single-fact lookups (use web_search, cheaper). "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use for small talk or ambient chatter. "
        "Do NOT use after web_search already gave a clear answer. "
        "Call once per turn. The answer is raw material, not a reply — "
        "read it, pick the one thread that matters, speak in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Specific research question in plain words. Include "
                    "comparison targets or scope if relevant."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "How many sources to rerank into the synthesis (default 8, max 12).",
            },
            "seed_url": {
                "type": "string",
                "description": (
                    "Optional URL to seed find_similar on. Use when the user "
                    "pasted a link and you want related pages."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.research", run_type="tool")
async def research(args):
    from backend.web.pipeline import run_web_research

    question = str(args.get("question") or "").strip() if isinstance(args, dict) else ""
    if not question:
        return text_content("research: question is required.")
    top_k = args.get("top_k") or 8
    try:
        top_k = max(3, min(int(top_k), 12))
    except (TypeError, ValueError):
        top_k = 8
    seed_url = args.get("seed_url") if isinstance(args, dict) else None
    seed = seed_url.strip() if isinstance(seed_url, str) and seed_url.strip() else None

    try:
        answer, trace = await run_web_research(
            question, top_k=top_k, seed_url=seed
        )
    except Exception:
        logger.exception("research: pipeline failure")
        return text_content("research unavailable.")

    if not answer.answer:
        reason = (answer.metadata or {}).get("reason", "")
        suffix = f" {reason}" if reason else ""
        if trace.merged_count == 0:
            return text_content(f"research: no hits.{suffix}")
        return text_content(f"research unavailable.{suffix}")

    variant = (answer.metadata or {}).get("variant", "merged")
    rendered = _render_research_answer(
        answer.answer,
        list(answer.sources),
        confidence=answer.confidence,
        dissent=answer.dissent,
        variant=variant,
    )
    return text_content(rendered)


SEND_BURST_INPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "description": (
                "Ordered list of UI items to render as one WhatsApp turn. "
                "Items render in order. At most 3 non-delay items per burst. "
                "Voice: lowercase, no em dashes. Each text body <=200 chars typical."
            ),
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["type", "body"],
                        "properties": {
                            "type": {"const": "text"},
                            "body": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1000,
                                "description": "Plain text bubble. Lowercase, no em dashes.",
                            },
                            "reply_to_message_id": {
                                "type": ["string", "null"],
                                "description": (
                                    "Optional WA message id to quote-reply to. "
                                    "Omit unless you specifically want this bubble "
                                    "to visually thread to a prior message."
                                ),
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "buttons"],
                        "properties": {
                            "type": {"const": "cta"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "buttons": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "description": (
                                    "1-3 reply buttons. Tapping a button sends "
                                    "its title back as the user's next inbound text. "
                                    "Use ONLY when the answer is a small known set "
                                    "(yes/no, pick from <=3 options). Not for "
                                    "open-ended questions."
                                ),
                                "items": {
                                    "type": "object",
                                    "required": ["id", "title"],
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 64,
                                            "description": "Short stable machine id, e.g. 'confirm_tz'.",
                                        },
                                        "title": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 20,
                                            "description": "User-facing label, <=20 chars.",
                                        },
                                    },
                                },
                            },
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "display_text", "url"],
                        "properties": {
                            "type": {"const": "cta_url"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "display_text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 20,
                                "description": "Label on the URL button (e.g. 'Open', 'Connect').",
                            },
                            "url": {"type": "string", "minLength": 1, "format": "uri"},
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "button_label", "sections"],
                        "properties": {
                            "type": {"const": "list"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "button_label": {"type": "string", "minLength": 1, "maxLength": 20},
                            "sections": {
                                "type": "array",
                                "minItems": 1,
                                "description": (
                                    "Up to 10 rows total across all sections. "
                                    "Use when there are >3 options to pick from. Rare."
                                ),
                                "items": {
                                    "type": "object",
                                    "required": ["title", "rows"],
                                    "properties": {
                                        "title": {"type": "string", "maxLength": 24},
                                        "rows": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "required": ["id", "title"],
                                                "properties": {
                                                    "id": {"type": "string", "maxLength": 64},
                                                    "title": {"type": "string", "maxLength": 24},
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"const": "image"},
                            "url": {
                                "type": "string",
                                "minLength": 1,
                                "format": "uri",
                                "description": (
                                    "Publicly accessible URL. Use this OR media_id, "
                                    "never both. Never invent a URL."
                                ),
                            },
                            "media_id": {
                                "type": "string",
                                "minLength": 1,
                                "description": (
                                    "WhatsApp media id returned by the image tool. "
                                    "Use this when threading a generated image into "
                                    "the burst. Use this OR url, never both."
                                ),
                            },
                            "caption": {"type": "string", "maxLength": 1024},
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                        "oneOf": [
                            {"required": ["url"]},
                            {"required": ["media_id"]},
                        ],
                    },
                    {
                        "type": "object",
                        "required": ["type", "seconds"],
                        "properties": {
                            "type": {"const": "delay"},
                            "seconds": {
                                "type": "number",
                                "minimum": 0.5,
                                "maximum": 4.0,
                                "description": (
                                    "Pause before next item, 0.5-4.0s. Use sparingly "
                                    "for pacing (greeting before a question, ack "
                                    "before advice). Never first or last item."
                                ),
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "const": "voice_response",
                                "description": (
                                    "VOICE-NOTE FLAG. Place first in the burst "
                                    "to deliver the whole burst as one WhatsApp "
                                    "voice note. The text bodies of the other "
                                    "items are concatenated and synthesized. "
                                    "USE WHEN: the user asked for voice; the "
                                    "inbound was itself a voice note (mirror "
                                    "back); the reply is personal, encouraging, "
                                    "moving, or a pep talk; the reply is a "
                                    "reflective read longer than two sentences; "
                                    "a soft check-in or nightly wind-down. "
                                    "DO NOT USE WHEN: the answer is a fact, a "
                                    "number, a time, a calendar item, a link, "
                                    "or a list; the burst includes a cta, "
                                    "cta_url, list, image, or document item "
                                    "(those cannot combine with voice); the "
                                    "user is in crisis or panic (text is more "
                                    "legible under stress); a one or two-word "
                                    "ack would do (a 4-word voice note is "
                                    "annoying). Hard cap 600 chars. On any "
                                    "synthesis failure the burst falls back to "
                                    "text. Saying 'here is a voice message' in "
                                    "text without this item is wrong."
                                ),
                            },
                        },
                    },
                ]
            },
        },
    },
}


@tool(
    "send_burst",
    (
        "TERMINATOR — the ONLY way to end a turn. Exactly one send_burst per "
        "turn, never twice, no silent exit. For ambient chatter, emit a "
        "single minimal text item ('k', 'noted') — still terminates. See "
        "`# HOW YOU USE WHATSAPP` in the system prompt for which widget to "
        "pick. A downstream voice filter strips em dashes, semicolons, and "
        "banned filler phrases and logs a violation, so produce clean text "
        "on first write."
    ),
    SEND_BURST_INPUT_SCHEMA,
)
@traceable(name="donna.tool.send_burst", run_type="tool")
async def send_burst(args):
    try:
        raw_messages = args.get("messages") if isinstance(args, dict) else []
        item_types = [
            (m.get("type") if isinstance(m, dict) else type(m).__name__)
            for m in (raw_messages or [])
        ]
        logger.info("send_burst.invoke: types=%s count=%d", item_types, len(item_types))
    except Exception:
        pass
    result = await send_burst_result(args)
    from .voice_synth import maybe_synthesize_voice
    await maybe_synthesize_voice()
    _fire_memory_hooks(_CURRENT_TRACE.get(), args)
    return result


DONNA_TOOLS = (
    recall,
    remember,
    watch,
    schedule,
    check_calendar,
    image,
    web_search,
    agentic_web_search,
    research,
    send_burst,
)
