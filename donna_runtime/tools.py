from __future__ import annotations

import json
import logging
from typing import Any

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)

from .hooks import _CURRENT_TRACE, _CURRENT_USER_ID, _fire_memory_hooks
from .langsmith_tracing import traceable
from .tool_logic import (
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


def _render_payload(payload: Any) -> str:
    if isinstance(payload, list):
        lines: list[str] = []
        for item in payload[:10]:
            if isinstance(item, dict):
                lines.append("- " + _render_dict_item(item))
            else:
                lines.append(f"- {item}")
        return "\n".join(lines)
    if isinstance(payload, dict):
        return json.dumps(payload, default=str, sort_keys=True)
    return str(payload)


def _render_dict_item(item: dict[str, Any]) -> str:
    for key in ("content", "fact", "rule", "title"):
        if item.get(key):
            prefix = f"{item.get('source')}: " if item.get("source") else ""
            return prefix + str(item[key])
    return json.dumps(item, default=str, sort_keys=True)


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
    if not user_id or not tz:
        return text_content("Timezone not updated.")
    res = await _set_timezone(
        user_id=user_id,
        timezone=tz,
        source=str(args.get("source") or "user_correction"),
    )
    return _tool_text(res, no_hits_text="Timezone not updated.", degraded_text="Timezone unavailable.")


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
        "brief is already in the system prompt."
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
                        "required": ["type", "url"],
                        "properties": {
                            "type": {"const": "image"},
                            "url": {
                                "type": "string",
                                "minLength": 1,
                                "format": "uri",
                                "description": "Publicly accessible URL. Never invent.",
                            },
                            "caption": {"type": "string", "maxLength": 1024},
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
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
    result = await send_burst_result(args)
    _fire_memory_hooks(_CURRENT_TRACE.get(), args)
    return result


DONNA_TOOLS = (
    recall_episodic,
    read_tracker,
    recall_graph,
    smart_recall,
    list_open_loops,
    list_calendar,
    log_observation,
    track_open_loop,
    close_open_loop,
    set_timezone,
    schedule_reminder,
    resolve_time_expression,
    read_situation_brief,
    send_burst,
)
