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
    voice_degraded: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """Render a ToolResult into chat content.

    When ``voice_degraded`` is True, the payload's `reason` is treated as
    the user-facing line (already Donna-voice) and forwarded verbatim.
    The ``degraded_text`` only applies when the reason is missing — i.e.
    a code path that returned `degraded()` without a message.
    """
    status = result.get("status")
    payload = result.get("payload")
    if status == "degraded":
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if voice_degraded and reason:
            return text_content(reason)
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
    "read_tracker",
    "Read-only tracker lookup by observation type (e.g. 'expense', 'mood'). "
    "Use period for local-time questions like today, this week, or last week. "
    "Returns JSON list of recent observations with local timestamps. "
    "Do NOT use for free-text memory recall or for non-countable events; "
    "use recall instead.",
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
    "context (use recall).",
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
    "-> check lunch time). Do NOT use for past events (use recall), "
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
    return _tool_text(
        res,
        no_hits_text="nothing on your calendar in that window.",
        degraded_text="calendar's offline on my end. try again in a sec.",
        voice_degraded=True,
    )


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
        return text_content("nothing new in your inbox.")
    res = await _list_gmail_recent(
        user_id=user_id,
        within_hours=int(args.get("within_hours") or 24),
        limit=int(args.get("limit") or 20),
        important_only=bool(args.get("important_only") or False),
    )
    return _tool_text(
        res,
        no_hits_text="nothing new in your inbox.",
        degraded_text="gmail's offline on my end. try again in a sec.",
        voice_degraded=True,
    )


@tool(
    "search_gmail",
    "Targeted live search across the user's full gmail history (Composio "
    "→ Gmail API). Use when the user asks for a specific email by sender, "
    "subject, or topic — especially when it might be older than the local "
    "mirror window. Accepts Gmail search syntax: from:/to:/subject:/"
    "after:YYYY/MM/DD/has:attachment/is:important/newer_than:7d. Hits are "
    "persisted to the local mirror so the next read is warm. Use for: "
    "'find the email from stripe last month', 'did X reply to Y', 'when "
    "was the last invoice from acme'. Do NOT use for 'any new mail?' / "
    "'what came in today?' (use list_gmail_recent — cheaper). Do NOT use "
    "when [INTEGRATIONS] shows google_gmail as not_connected.",
    {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Gmail search query. Examples: 'from:stripe.com', "
                    "'subject:invoice after:2026/04/01', "
                    "'from:saurabh has:attachment'."
                ),
            },
            "limit": {"type": "integer", "default": 10},
        },
    },
)
@traceable(name="donna.tool.search_gmail", run_type="tool")
async def search_gmail(args):
    from backend.memory.tools.search_gmail import (
        search_gmail as _search_gmail,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("can't search your gmail right now.")
    query = str(args.get("query") or "").strip()
    if not query:
        return text_content("search needs a query — e.g. 'from:stripe.com'.")
    limit = int(args.get("limit") or 10)
    res = await _search_gmail(user_id=user_id, query=query, limit=limit)
    return _tool_text(
        res,
        no_hits_text="couldn't find anything matching that.",
        degraded_text="gmail's slow on my end. try again in a sec.",
        voice_degraded=True,
    )


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
    return _tool_text(
        res,
        no_hits_text="can't find that thread. probably archived or deleted.",
        degraded_text="gmail's slow right now. try again in a sec.",
        voice_degraded=True,
    )


@tool(
    "composio_search_tools",
    "Discover the right Composio tool slug for an integration use-case "
    "you don't already have a typed wrapper for. Use when the user asks "
    "for an action against a connected SaaS provider (slack, notion, "
    "linear, etc.) and you don't recognize the right tool name. Do NOT "
    "use for gmail or calendar — those have typed tools "
    "(list_gmail_recent, read_gmail_thread, list_calendar). Returns a "
    "ranked list of tool slugs with descriptions; pass the chosen slug "
    "to composio_execute_tool.",
    {
        "type": "object",
        "properties": {
            "use_case": {
                "type": "string",
                "description": "Plain-language description of what you want to do.",
            },
        },
        "required": ["use_case"],
    },
)
@traceable(name="donna.tool.composio_search_tools", run_type="tool")
async def composio_search_tools(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot search: no user_id in scope.")
    use_case = str(args.get("use_case") or "").strip()
    if not use_case:
        return text_content("Cannot search: 'use_case' is required.")

    res = await composio_meta.search_tools(user_id=user_id, use_case=use_case)
    import json as _json
    return text_content(_json.dumps(res, indent=2))


@tool(
    "composio_execute_tool",
    "Generic Composio tool invocation. Use for SaaS actions that lack a "
    "typed Donna wrapper. Get the right tool_slug from composio_search_tools "
    "first. Do NOT use for gmail/calendar reads — list_gmail_recent, "
    "read_gmail_thread, list_calendar are faster and structured.",
    {
        "type": "object",
        "properties": {
            "tool_slug": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["tool_slug", "arguments"],
    },
)
@traceable(name="donna.tool.composio_execute_tool", run_type="tool")
async def composio_execute_tool(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot execute: no user_id in scope.")
    slug = str(args.get("tool_slug") or "").strip()
    if not slug:
        return text_content("Cannot execute: 'tool_slug' is required.")
    raw_args = args.get("arguments") or {}
    if not isinstance(raw_args, dict):
        return text_content("Cannot execute: 'arguments' must be an object.")

    res = await composio_meta.execute_tool(
        user_id=user_id, tool_slug=slug, arguments=raw_args
    )
    import json as _json
    return text_content(_json.dumps(res, indent=2)[:4000])


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

    # Best-effort: hand the freshly-written row to the observation
    # spawner. Never block the original tool's reply on spawner failure.
    try:
        obs_id = _extract_observation_id(res)
        if obs_id:
            await _spawn_from_observation(
                user_id=user_id,
                obs_id=obs_id,
                obs_type=obs_type,
                fields=fields,
                raw=str(args.get("raw") or ""),
                event_time=str(args.get("event_time") or ""),
            )
    except Exception:
        logger.exception("log_observation: spawner hook raised")

    return _tool_text(res, no_hits_text="Observation not logged.", degraded_text="Observation unavailable.")


def _extract_observation_id(res: Any) -> str | None:
    """Pull the observation id out of the ToolResult shape ({status, payload})."""
    if not isinstance(res, dict):
        return None
    if res.get("status") != "ok":
        return None
    payload = res.get("payload")
    if isinstance(payload, dict):
        return payload.get("id")
    return None


async def _spawn_from_observation(
    *,
    user_id: str,
    obs_id: str,
    obs_type: str,
    fields: dict,
    raw: str,
    event_time: str,
) -> None:
    """Fetch the persisted Observation row and feed the spawner.

    Done in a fresh session so the spawner sees the committed event_time
    + enriched fields rather than relying on the in-process tool args.
    """
    try:
        from sqlalchemy import select

        from backend.db.models import Observation
        from backend.db.session import async_session
    except Exception:
        return
    obs_row = None
    try:
        async with async_session() as session:
            obs_row = (
                await session.execute(
                    select(Observation).where(Observation.id == obs_id)
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception("log_observation: spawner row fetch failed id=%s", obs_id)
    if obs_row is None:
        return
    from proactive.spawners import observation as observation_spawner

    await observation_spawner.maybe_spawn(obs_row, user_id)


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
    "clear_pending_note",
    "Dismiss a queued proactive note from the PENDING NOTES block. Use "
    "when this turn's send_burst already addresses what the note was "
    "queued for (reason='delivered'), when the note is no longer worth "
    "surfacing (reason='irrelevant'), or when the user brought up the "
    "topic themselves first (reason='superseded_by_user'). Do NOT use "
    "for notes you have not actually consumed in this turn — the brain "
    "is the only consumer of pending notes, and silently clearing is "
    "indistinguishable from forgetting.",
    {
        "type": "object",
        "required": ["note_id"],
        "properties": {
            "note_id": {"type": "string"},
            "reason": {
                "type": "string",
                "enum": ["delivered", "irrelevant", "superseded_by_user"],
                "description": "Default: delivered.",
            },
        },
    },
)
@traceable(name="donna.tool.clear_pending_note", run_type="tool")
async def clear_pending_note(args):
    from proactive.dispatcher import clear_pending_note as _clear

    note_id = str(args.get("note_id") or "").strip()
    reason = str(args.get("reason") or "delivered").strip() or "delivered"
    if not note_id:
        return text_content("clear_pending_note: note_id is required.")
    ok = await _clear(note_id, reason=reason)
    if ok:
        return text_content(f"Pending note {note_id} cleared as {reason}.")
    return text_content(
        f"Pending note {note_id} not cleared (already resolved or unknown id)."
    )


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
    "Generate a one-tap consent link for ONE OR MANY Composio toolkits. Pass "
    "any toolkit slug(s): google's are gmail, googlecalendar, googledrive; "
    "others include slack, notion, linear, github, asana, hubspot, "
    "salesforce, intercom, etc. Multiple toolkits in one call are bundled "
    "into a single redirect chain — the user taps once, walks each consent "
    "page in order, and lands back at done. Use when the [INTEGRATIONS] "
    "context block shows a needed toolkit as not_connected and the user "
    "asks for something requiring it, or asks to connect explicitly. Do NOT "
    "use when the toolkit is already connected, when status is 'pending' (a "
    "link is already in flight — do not nag), or when the user is mid-task "
    "and a connect prompt would derail them. Pass ``intent`` with the "
    "user's actual ask in plain words — once the connection lands, that "
    "ask gets answered automatically without the user re-prompting. Returns "
    "a one-line consent message containing a single URL — forward verbatim.",
    {
        "type": "object",
        "properties": {
            "toolkits": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Composio toolkit slug(s). Examples: gmail, "
                    "googlecalendar, googledrive, slack, notion, linear, "
                    "github, asana, hubspot, salesforce."
                ),
            },
            "intent": {
                "type": "string",
                "description": (
                    "What the user actually wants done once connected, in "
                    "their words. E.g. 'summarize my gmail this week', "
                    "'check if i have anything tomorrow morning'. Leave "
                    "empty when the user only asked to connect (no task "
                    "behind it). When set, this exact ask is replayed as a "
                    "fresh turn the moment the integration lands."
                ),
            },
        },
        "required": ["toolkits"],
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
    if "products" in args and "toolkits" not in args:
        # Hard-correct the model: only `toolkits` is in the schema.
        return text_content(
            "connect_integration takes 'toolkits', not 'products'. "
            "retry with toolkits=[...]."
        )
    raw = args.get("toolkits") or []
    if not isinstance(raw, list):
        raw = [raw]
    toolkits = [str(t).strip() for t in raw if str(t).strip()]
    if not toolkits:
        return text_content("Cannot connect: 'toolkits' is required.")

    intent = str(args.get("intent") or "").strip() or None

    res = await _connect(user_id=user_id, toolkits=toolkits)
    status = res.get("status")
    if status == "already_connected":
        return text_content("already connected. nothing to do.")
    if status == "error":
        msg = (res.get("message") or "unknown").strip()
        return text_content(f"connect failed: {msg}. try again in a sec.")

    if intent:
        try:
            from backend.integrations.pending_intents import enqueue_intent
            await enqueue_intent(user_id=user_id, toolkits=toolkits, intent=intent)
        except Exception:
            logger.exception(
                "connect_integration: pending intent enqueue failed user=%s",
                user_id,
            )

    # Backend `_consent_message` is already Donna-voice; forward verbatim.
    return text_content(res.get("message") or f"tap: {res.get('url')}")


@tool(
    "check_integration_status",
    "Read-only ground truth for the user's Composio integrations. Lists "
    "every connected_account on Composio's side AND merges with the local "
    "integrations DB so you can answer 'is gmail working?' or 'why isn't "
    "my slack connected yet?' honestly. Reconciles drift (e.g. user "
    "completed OAuth in browser but our background watcher missed it) by "
    "upgrading local rows to connected when Composio says ACTIVE. Use when "
    "the user says 'didn't work' / 'still broken' / 'retry' AFTER a previous "
    "connect_integration, when the user asks 'is X connected' or 'what "
    "integrations do I have', or to verify ground truth before re-issuing "
    "a chain (NEVER re-issue connect_integration blindly — call this first). "
    "Do NOT use on first connect (the [INTEGRATIONS] block already shows "
    "state), more than once per turn (second call returns identical data), "
    "or as a way to poll OAuth completion (the watcher does that). Returns "
    "per-toolkit status + a one-line summary.",
    {
        "type": "object",
        "properties": {
            "toolkits": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional filter — only check these toolkit slugs "
                    "(e.g. ['gmail', 'slack']). Omit to check everything "
                    "the user has touched."
                ),
            }
        },
    },
)
@traceable(name="donna.tool.check_integration_status", run_type="tool")
async def check_integration_status(args):
    from backend.memory.tools.check_integration_status import (
        check_integration_status as _check,
    )

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot check: no user_id in scope.")
    raw = (args or {}).get("toolkits") or []
    if not isinstance(raw, list):
        raw = [raw]
    toolkits = [str(t).strip() for t in raw if str(t).strip()] or None

    res = await _check(user_id=user_id, toolkits=toolkits)
    import json as _json
    payload = {
        "summary": res.get("summary"),
        "toolkits": res.get("toolkits") or {},
    }
    return text_content(_json.dumps(payload, indent=2))


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
        "Record a user-stated observation, commitment, or timezone into memory. "
        "This wrapper routes to the right backend. Bias toward using it when "
        "the current user message gives information Donna should hold onto. "
        "For kind='observation': always pass observation_type. Pass fields when "
        "the event has obvious numeric/structured data — expense {amount_usd: 6}, "
        "meal {item, calories}, sleep {hours: 7}, mood {score: 4}, exercise "
        "{minutes, type}, alcohol {count, unit}. For casual observations with no "
        "natural numeric shape (notes, social events, ambient feelings), "
        "fields may be empty {} — the `content` text captures the meaning. "
        "For kind='commitment': use when the user states they will do something "
        "with no clock attached (\"i'll send the doc\", \"need to call mom\"). "
        "When a clock is named (\"by friday\", \"tonight\", \"in an hour\"), "
        "use attend() instead. Resolution is detected automatically from chat. "
        "Profile facts (name, city, profession, age, etc.) are handled "
        "automatically by a pre-turn detector and the post-turn extractor — "
        "do NOT call this with kind='fact' or kind='preference'. Those kinds "
        "are removed. The legacy kinds 'open_loop' and 'loop_closed' are also "
        "removed — use 'commitment' instead, and never try to close one. "
        "Do NOT call this to re-save things that only came from USER MODEL, "
        "SITUATION BRIEF, runtime context, or a recall result. "
        "Do NOT invent values the user did not state (no fabricated amounts, "
        "timezones). "
        "Do NOT use for timed reminders (use schedule) or for things better "
        "surfaced as a dashboard attention (use watch). "
        "Do NOT call twice for the same observation/commitment/timezone within one turn."
    ),
    {
        "type": "object",
        "required": ["kind", "content"],
        "properties": {
            "kind": {
                "type": "string",
                "description": "observation, commitment, or timezone.",
            },
            "content": {"type": "string"},
            "observation_type": {"type": "string"},
            "fields": {"type": "object"},
            "tags": {"type": "object"},
            "event_time": {"type": "string"},
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
            + ", ".join(["observation", "commitment", "timezone"])
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
                "OBSERVATION REJECTED. 'observation_type' is required. Do NOT "
                "claim it was logged. Common types: expense, meal, mood, sleep, "
                "habit, exercise, symptom, alcohol, note. Example: "
                "observation_type='alcohol', fields={'count': 5, 'unit': 'beers'}."
            )
        # Casual observations (alcohol, social events, notes) often have no
        # obvious numeric `fields`. We accept empty `fields` — the `raw`
        # text carries the meaning, and pattern miners still count by type.
        # Structured types (expense, meal, sleep) should still pass fields,
        # but the tool description handles that nudge; we don't reject here.
        res = await _log_observation(
            user_id=user_id,
            type=obs_type,
            fields=fields,
            tags=args.get("tags") if isinstance(args.get("tags"), dict) else {},
            raw=content,
            event_time=str(args.get("event_time") or ""),
            confidence=_numeric_confidence(args.get("confidence")),
        )
        return _result_text(
            "remembered observation",
            res,
            no_hits_text=(
                "OBSERVATION NOT RECORDED. Do NOT claim you logged it. "
                "Note the user without saying 'logged'."
            ),
            degraded_text=(
                "OBSERVATION FAILED (backend error). Do NOT claim you logged "
                "it. Acknowledge the user without saying 'logged'."
            ),
        )

    if kind in {"open_loop", "commitment"}:
        # open_loops as a separate concept is being retired — the table
        # was write-only in practice (close_open_loop never got called by
        # the brain). Both kinds now land as observations of type
        # 'commitment' so the LP synthesizer can surface unresolved ones
        # and the post-turn extractor can detect resolution mentions.
        from backend.memory.tools.log_observation import log_observation as _log_observation

        tags = args.get("tags") if isinstance(args.get("tags"), dict) else {}
        tags = {**tags, "source": "stated", "resolved": False}
        res = await _log_observation(
            user_id=user_id,
            type="commitment",
            fields={"text": content},
            tags=tags,
            raw=content,
            event_time=args.get("event_time"),
            confidence=_numeric_confidence(args.get("confidence")),
        )
        return _result_text("remembered commitment", res, no_hits_text="Commitment not recorded.")

    if kind == "loop_closed":
        # Resolution detection is moving to the post-turn extractor.
        # Reply degraded so the model doesn't claim it closed something.
        return text_content(
            "Memory not recorded: kind='loop_closed' has been removed. "
            "Resolution of stated commitments is now detected automatically "
            "from chat. Drop the tool call; just reply."
        )

    if kind == "timezone":
        from backend.memory.tools.set_timezone import set_timezone as _set_timezone

        tz = str(args.get("timezone") or content).strip()
        res = await _set_timezone(user_id=user_id, timezone=tz, source="user_correction")
        return _result_text("remembered timezone", res, no_hits_text="Timezone not updated.")

    return text_content(
        f"Memory not recorded: unsupported kind {kind!r}. "
        f"Valid kinds: observation, commitment, timezone."
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
                                    "Voice is RARE — text is the default reply "
                                    "mode in every turn. USE WHEN: the user "
                                    "explicitly asked for voice ('send me a "
                                    "voice', 'voice me', 'say it out loud'); "
                                    "the reply is genuinely personal and "
                                    "emotionally weighted (a pep talk, a soft "
                                    "check-in at a hard moment, a longform "
                                    "reflective read more than two sentences). "
                                    "DO NOT USE WHEN: the inbound was a voice "
                                    "note but the reply is short, factual, or "
                                    "operational (the user dictated for their "
                                    "own convenience, not to request voice "
                                    "back — mirroring is wrong); the answer is "
                                    "a fact, a number, a time, a calendar "
                                    "item, a link, or a list; the burst "
                                    "includes a cta, cta_url, list, image, or "
                                    "document item (those cannot combine with "
                                    "voice); the user is in crisis or panic "
                                    "(text is more legible under stress); a "
                                    "one or two-word ack would do (a 4-word "
                                    "voice note is annoying). Hard cap 600 "
                                    "chars. On any synthesis failure the "
                                    "burst falls back to text. Saying 'here "
                                    "is a voice message' in text without this "
                                    "item is wrong."
                                ),
                            },
                        },
                    },
                ]
            },
        },
    },
}


async def _create_and_queue_attention(
    *, intent: str, user_id: str | None, origin: str, label: str
) -> dict[str, Any]:
    """Shared core for `attend` / `remind` / future attention-creating tools.

    Runs the author pipeline, materializes the first fire when the cadence
    is queueable (ONE_SHOT or SCHEDULED), and returns a small dict the
    individual tool wrappers turn into user-facing text. Keeps the failure
    modes uniform across entry points.
    """
    if not user_id:
        return {"status": "error", "reason": "no_user_id"}
    if not intent:
        return {"status": "error", "reason": "missing_intent"}

    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session as _session_factory
        from donna.attention.firing import materialize_next_fire
        from donna.attention.schema import AttentionOrigin
        from donna.attention.tools import create_attention
        from donna.attention.vocabulary import CadenceType
    except Exception as exc:
        logger.exception("%s: backend imports unavailable", label)
        return {"status": "error", "reason": f"imports:{type(exc).__name__}"}

    try:
        result = await create_attention(intent, user_id=user_id, auto_live=True)
    except Exception as exc:
        logger.exception("%s: create_attention failed", label)
        return {"status": "error", "reason": f"author:{type(exc).__name__}"}

    attention = result.attention

    # Near-match dedup: ``create_attention`` returns ``reused=True`` when
    # a recent LIVE PING with the same normalised subject already exists.
    # Skip every "wire it up" step (postgres mirror, schedule fire,
    # DonnaInstance materialise) — they're already done for the
    # original attention. Just confirm the merge to the caller.
    if result.reused:
        return {
            "status": "reused",
            "attention_id": str(attention.id),
            "title": attention.spec.title,
            "card": attention.spec.card.value,
            "cadence_type": attention.spec.cadence.type.value,
            "reused": True,
        }

    if origin == "donna":
        attention = attention.model_copy(
            update={"origin": AttentionOrigin.SHADOW_INFERRED}
        )

    try:
        async with _session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return {"status": "error", "reason": "user_not_found"}
            phone = getattr(user, "phone", None)
            tz = getattr(user, "timezone", None) or "Asia/Singapore"
            if not phone:
                return {"status": "error", "reason": "missing_phone"}
    except Exception as exc:
        logger.exception("%s: user lookup failed", label)
        return {"status": "error", "reason": f"db:{type(exc).__name__}"}

    # Dual-write to postgres so other replicas / the schedule worker see
    # the attention. The file store was already written by
    # ``create_attention`` above and remains the dev / cli fallback. We
    # don't fail the user request on mirror failure — the fire still
    # queues via DonnaSchedule, which is the path that actually delivers.
    try:
        from donna.attention.postgres_store import persist_attention

        await persist_attention(attention, user_id=user_id)
    except Exception:
        logger.exception("%s: postgres mirror write failed", label)

    cadence_type = attention.spec.cadence.type
    queueable = cadence_type in (CadenceType.ONE_SHOT, CadenceType.SCHEDULED)
    schedule_id: str | None = None
    if queueable:
        try:
            schedule_id = await materialize_next_fire(
                attention,
                user_id=user_id,
                user_phone=phone,
                user_tz=tz,
                origin=origin,
            )
        except Exception as exc:
            logger.exception("%s: materialize_next_fire failed", label)
            return {
                "status": "partial",
                "attention_id": str(attention.id),
                "reason": f"queue:{type(exc).__name__}",
            }
        if schedule_id is None:
            return {"status": "past_trigger", "attention_id": str(attention.id)}

    # For tracker-shaped cards (TALLY/EVENT_STREAM), do the same
    # post-accept work the dashboard accept handler does: materialize a
    # DonnaInstance(primitive=track) so observations route correctly,
    # and recompose the dashboard so the tracker-grid lands on the next
    # poll. Best-effort — failures here don't void the attention.
    instance_id: str | None = None
    instance_created = False
    try:
        from backend.dashboard.actions import (
            _maybe_materialize_instance,
            _spawn_recompose,
        )

        instance_id, instance_created = await _maybe_materialize_instance(
            user_id=user_id, attention=attention
        )
        if instance_id is not None:
            # Only recompose when a tracker actually materialized — for
            # PING / OPEN_LOOP / BRIEF cards there's nothing the
            # dashboard would surface differently right now. Fire-and-
            # forget so the brain turn doesn't block on a 60s LLM call.
            _spawn_recompose(user_id=user_id)
    except Exception:
        logger.exception("%s: dashboard wireup failed (non-fatal)", label)

    return {
        "status": "ok",
        "attention_id": str(attention.id),
        "title": attention.spec.title,
        "card": attention.spec.card.value,
        "cadence_type": cadence_type.value,
        "schedule_id": schedule_id,
        "instance_id": instance_id,
        "instance_created": instance_created,
    }


@tool(
    "attend",
    (
        "Create an attention — the SINGLE creation primitive for anything "
        "Donna will surface to the user in the future. One-shot reminders, "
        "recurring nudges, standing watches, weekly briefs, calendar prep: "
        "all collapse to this one tool. The author parses the intent and "
        "picks the right card (ping / event_stream / tally / brief / "
        "prep_doc / open_loop) and cadence (one_shot / scheduled / on_event) "
        "for you — do not pre-classify the intent yourself. "
        "Returns the attention_id; pass it to cancel_attention or "
        "snooze_attention. Origin defaults to 'user'; pass origin='donna' "
        "when Donna is proactively scheduling on the user's behalf. "
        "\n\n"
        "ANTICIPATE. When the user mentions something that obviously sets "
        "up a future moment, schedule the attention yourself with "
        "origin='donna'. Don't wait to be asked. Examples of obvious "
        "anticipations:\n"
        "- user mentions 'meeting Aniroodh tomorrow at lunch' → "
        "origin='donna' attend('prep me 30 min before lunch with "
        "Aniroodh tomorrow') because they'll want context heading in.\n"
        "- user mentions 'shipping deploy at 3am' → origin='donna' "
        "attend('check in tomorrow morning on how the canopy ship went').\n"
        "- user mentions 'I have a midterm in 3 days' → origin='donna' "
        "attend('the morning of the midterm, surface a quick ready check').\n"
        "- user mentions 'I'm writing the YC application this weekend' → "
        "origin='donna' attend('check in saturday morning on YC progress').\n"
        "The bar for anticipation: would a thoughtful friend write it down "
        "without being asked? If yes, do it. If you're 50/50, do it — "
        "the user can cancel_attention if it's wrong. Silence on something "
        "obvious is worse than a slightly off attention.\n"
        "\n"
        "Use whenever the user asks to be reminded, watched, briefed, "
        "prepped, or pinged at a time or on a cadence. Examples: 'remind "
        "me at 5pm to call mom' (one-shot ping), 'every weekday at 9am "
        "journal' (recurring ping), 'keep an eye on poke launch updates' "
        "(standing event_stream), 'brief me on fundraising every friday' "
        "(weekly brief), 'prep me 15 min before sarah 1:1' (calendar prep). "
        "Do NOT use for open-ended commitments with no time or cadence "
        "('text luca' — that is track_open_loop). Do NOT use for "
        "past events (memory, not scheduling). For anticipations where "
        "the user didn't give an exact time, infer a sensible default "
        "(morning of, 30 min before, end of day) — do NOT pause to ask."
    ),
    {
        "type": "object",
        "required": ["intent"],
        "properties": {
            "intent": {
                "type": "string",
                "description": (
                    "Natural instruction in the user's words. Pass the "
                    "phrasing through unchanged — the author parses time / "
                    "cadence / subject / sources. Examples: 'remind me at "
                    "5pm to call mom', 'every weekday at 9am journal', "
                    "'keep an eye on poke launch updates', 'brief me on "
                    "fundraising every friday', 'prep me 15 minutes before "
                    "sarah 1:1'."
                ),
            },
            "origin": {
                "type": "string",
                "enum": ["user", "donna"],
                "description": (
                    "'user' when the user explicitly asked, 'donna' when "
                    "Donna is proactively scheduling. Defaults to 'user'."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.attend", run_type="tool")
async def attend(args):
    user_id = _current_user_id()
    intent = str(args.get("intent") or "").strip()
    origin = str(args.get("origin") or "user").lower()
    if origin not in ("user", "donna"):
        origin = "user"

    result = await _create_and_queue_attention(
        intent=intent, user_id=user_id, origin=origin, label="attend"
    )
    return _render_attention_result(result)


def _render_attention_result(result: dict[str, Any]):
    status = result.get("status")
    if status == "reused":
        title = result.get("title") or "(untitled)"
        aid = result.get("attention_id") or "?"
        return text_content(
            f"attention reused: '{title}' is already live (attention_id={aid}). "
            "tell the user you already have this one running and you're "
            "keeping the existing schedule, not adding a duplicate."
        )
    if status == "ok":
        title = result.get("title") or "(untitled)"
        cadence = result.get("cadence_type") or "?"
        card = result.get("card") or "?"
        aid = result.get("attention_id") or "?"
        return text_content(
            f"attention created: '{title}' (card={card}, cadence={cadence}, "
            f"attention_id={aid})"
        )
    if status == "past_trigger":
        return text_content(
            "attention not queued: the parsed time is in the past. Ask the "
            "user to clarify the time."
        )
    if status == "partial":
        aid = result.get("attention_id") or "?"
        reason = result.get("reason") or "unknown"
        return text_content(
            f"attention partly created (saved as {aid}, fire not queued: "
            f"{reason}). Tell the user to retry."
        )
    reason = result.get("reason") or "unknown"
    if reason == "no_user_id":
        return text_content(
            "attention not created: no user_id in scope. Runtime bug — report it."
        )
    if reason == "missing_intent":
        return text_content(
            "attention not created: 'intent' is required. Pass a natural "
            "instruction in the user's words, e.g. 'remind me at 5pm to "
            "call mom' or 'keep an eye on the poke launch updates'."
        )
    if reason == "user_not_found":
        return text_content("attention not created: user not found.")
    if reason == "missing_phone":
        return text_content("attention not created: user missing phone.")
    return text_content(f"attention not created: {reason}.")


@tool(
    "list_attentions",
    (
        "List the user's pending attentions (unfired attention-linked "
        "schedules — reminders, scheduled watches, recurring nudges). "
        "Returns attention_id, fire_at, message, and recurrence info per row. "
        "Use when the user asks 'what reminders do I have', 'when is the next "
        "ping', 'what are you watching', or before calling cancel_attention / "
        "snooze_attention so you have the right id. "
        "Do NOT use as a fishing expedition — only when the user is asking "
        "about their pending attentions or you need to discover an "
        "attention_id to act on."
    ),
    {"type": "object", "properties": {}},
)
@traceable(name="donna.tool.list_attentions", run_type="tool")
async def list_attentions(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("No attentions.")
    try:
        from donna.attention.firing import list_pending_for_user
    except Exception:
        logger.exception("list_attentions: import failed")
        return text_content("Attentions unavailable.")
    try:
        rows = await list_pending_for_user(user_id)
    except Exception:
        logger.exception("list_attentions: query failed")
        return text_content("Attentions unavailable.")
    if not rows:
        return text_content("No attentions.")
    lines: list[str] = []
    for r in rows[:20]:
        meta = r.get("recurrence_meta") or {}
        cad_type = meta.get("cadence_type") or "one_shot"
        line = (
            f"- {r['fire_at']}  ({cad_type})  {r.get('message') or '(no message)'}"
            f"  [attention_id={r.get('attention_id')}]"
        )
        lines.append(line)
    if len(rows) > 20:
        lines.append(f"(showing 20 of {len(rows)})")
    return text_content("\n".join(lines))


@tool(
    "cancel_attention",
    (
        "Cancel an attention by attention_id. Deletes any pending fires and "
        "marks the attention resolved. Idempotent — safe to call twice. "
        "Use when the user explicitly says to cancel / stop / forget a "
        "reminder, watch, or scheduled nudge. Get the attention_id from "
        "list_attentions first if you do not have it. "
        "Do NOT cancel without an explicit user instruction. Do NOT use to "
        "snooze (use snooze_attention). Do NOT use to pause temporarily — "
        "cancel is permanent."
    ),
    {
        "type": "object",
        "required": ["attention_id"],
        "properties": {
            "attention_id": {
                "type": "string",
                "description": "The id returned by attend / list_attentions.",
            },
        },
    },
)
@traceable(name="donna.tool.cancel_attention", run_type="tool")
async def cancel_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    if not user_id:
        return text_content("Cancel failed: no user_id in scope.")
    if not attention_id:
        return text_content(
            "Cancel failed: 'attention_id' is required. Call list_attentions "
            "to discover it first."
        )
    try:
        from donna.attention.firing import cancel_pending_fires
        from donna.attention.postgres_store import update_attention_status
        from donna.attention.schema import AttentionStatus
        from donna.attention.tools import resolve_attention
    except Exception:
        logger.exception("cancel_attention: imports unavailable")
        return text_content("Cancel failed: backend unavailable.")
    try:
        deleted = await cancel_pending_fires(attention_id)
    except Exception:
        logger.exception("cancel_attention: db delete failed")
        return text_content("Cancel failed: db error.")
    try:
        resolve_attention(attention_id)
    except Exception:
        logger.info("cancel_attention: file-store status update skipped")
    try:
        await update_attention_status(attention_id, AttentionStatus.RESOLVED)
    except Exception:
        logger.exception("cancel_attention: postgres status update failed")
    if deleted == 0:
        return text_content(
            f"Cancel: nothing pending for attention_id={attention_id} "
            f"(already fired or unknown)."
        )
    return text_content(
        f"Cancelled attention_id={attention_id} ({deleted} pending fire(s) removed)."
    )


@tool(
    "snooze_attention",
    (
        "Push a pending attention's next fire forward by N minutes. Returns "
        "the new fire time. Idempotent per call — calling twice snoozes "
        "twice. "
        "Use when the user says 'snooze 10 min', 'remind me 30 min later', "
        "'push that back an hour'. Get the attention_id from list_attentions "
        "if you do not have it. "
        "Do NOT use for cancellation (use cancel_attention). Do NOT use to "
        "set an absolute new time — create a fresh attention via attend "
        "instead."
    ),
    {
        "type": "object",
        "required": ["attention_id", "minutes"],
        "properties": {
            "attention_id": {"type": "string"},
            "minutes": {
                "type": "integer",
                "description": "How many minutes to push the next fire forward (1..1440).",
            },
        },
    },
)
@traceable(name="donna.tool.snooze_attention", run_type="tool")
async def snooze_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    try:
        minutes = int(args.get("minutes") or 0)
    except Exception:
        return text_content("Snooze failed: 'minutes' must be an integer.")
    if not user_id:
        return text_content("Snooze failed: no user_id in scope.")
    if not attention_id:
        return text_content("Snooze failed: 'attention_id' is required.")
    if minutes <= 0 or minutes > 60 * 24:
        return text_content("Snooze failed: 'minutes' must be 1..1440.")
    try:
        from donna.attention.firing import snooze_pending_fires
    except Exception:
        logger.exception("snooze_attention: import failed")
        return text_content("Snooze failed: backend unavailable.")
    try:
        new_fire = await snooze_pending_fires(attention_id, by_seconds=minutes * 60)
    except Exception:
        logger.exception("snooze_attention: db update failed")
        return text_content("Snooze failed: db error.")
    if new_fire is None:
        return text_content(
            f"Snooze: nothing pending for attention_id={attention_id}."
        )
    return text_content(
        f"snoozed attention_id={attention_id} by {minutes} min "
        f"(new fire at {new_fire.isoformat()})"
    )


@tool(
    "accept_attention",
    (
        "Accept an OFFERED attention so it goes LIVE and starts running. "
        "OFFERED attentions appear in the per-turn ATTENTIONS WAITING block "
        "with their attention_id. The user accepting one looks like 'yes', "
        "'do it', 'start it', 'go ahead', or a clear contextual yes after "
        "you proposed the structure last turn or this turn. "
        "Use ONLY when the user agreed to a specific OFFERED attention from "
        "ATTENTIONS WAITING — pass that exact attention_id. "
        "Do NOT use for cancellation (use cancel_attention). Do NOT use to "
        "create a brand new attention (use attend). Do NOT call without an "
        "explicit user yes — never accept on the user's behalf. Do NOT pass "
        "an attention_id that isn't in ATTENTIONS WAITING — accept_attention "
        "only flips OFFERED -> LIVE."
    ),
    {
        "type": "object",
        "required": ["attention_id"],
        "properties": {
            "attention_id": {
                "type": "string",
                "description": (
                    "The attention_id from ATTENTIONS WAITING in your per-turn context."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.accept_attention", run_type="tool")
async def accept_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    if not user_id:
        return text_content("Accept failed: no user_id in scope.")
    if not attention_id:
        return text_content(
            "Accept failed: 'attention_id' is required. The id is shown in "
            "ATTENTIONS WAITING."
        )
    try:
        from donna.attention.promote import accept_offer
    except Exception:
        logger.exception("accept_attention: imports unavailable")
        return text_content("Accept failed: backend unavailable.")
    try:
        updated = accept_offer(attention_id)
    except Exception:
        logger.exception("accept_attention: store update failed")
        return text_content("Accept failed: store error.")
    if updated is None:
        return text_content(
            f"Accept: attention_id={attention_id} is not OFFERED right now "
            "(already accepted, expired, or unknown)."
        )
    title = getattr(getattr(updated, "spec", None), "title", "") or "attention"
    return text_content(
        f"accepted attention_id={attention_id} ({title}) — status LIVE."
    )


@tool(
    "update_dashboard",
    (
        "Recompose the user's home dashboard from current state and persist "
        "it. Use when the user explicitly asks for a fresh read on their "
        "day ('redo my dashboard', 'refresh my home screen') or when a "
        "genuine state shift just landed (a major open loop closed, a new "
        "tracker started, a permission granted) and the previous manifest "
        "is now wrong. Does NOT change WhatsApp output — purely updates "
        "the web dashboard. Do NOT use to acknowledge a small action, "
        "after every recall, or when nothing material has changed since "
        "the last manifest. Returns a one-line confirmation."
    ),
    {
        "type": "object",
        "properties": {
            "trigger": {
                "type": "string",
                "description": (
                    "Short label for why this recompose was fired, e.g. "
                    "'manual', 'open_loop_closed', 'integration_connected'. "
                    "Stored alongside the manifest for debugging."
                ),
            }
        },
        "required": ["trigger"],
    },
)
async def update_dashboard(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("dashboard: no user_id in scope.")
    trigger = ""
    if isinstance(args, dict):
        trigger = str(args.get("trigger") or "").strip()
    if not trigger:
        trigger = "manual"
    try:
        from backend.dashboard.compose import compose_manifest
        from backend.dashboard.store import upsert_manifest
    except Exception:
        logger.exception("update_dashboard: import failed")
        return text_content("dashboard: subsystem unavailable.")
    try:
        plan = await compose_manifest(user_id=user_id, trigger=trigger)
    except Exception:
        logger.exception("update_dashboard: compose raised user_id=%s", user_id)
        return text_content("dashboard: compose failed (logged).")
    if plan is None:
        return text_content("dashboard: compose failed (logged).")
    try:
        await upsert_manifest(user_id, plan, trigger=trigger)
    except Exception:
        logger.exception("update_dashboard: upsert raised user_id=%s", user_id)
        return text_content("dashboard: persist failed (logged).")
    thesis_preview = (plan.thesis or "").strip()[:60]
    return text_content(f"dashboard updated · {thesis_preview}")


def mint_dashboard_url(user_id: str, *, reason: str = "user_request") -> str | None:
    """Mint a fresh 5-minute magic link for the user's dashboard.

    Returns the URL on success, None when the subsystem is unavailable or
    DASHBOARD_BASE_URL is not configured. Logs at info on success, warning
    on missing config, exception on mint failure. Used by both the
    send_dashboard_link tool and the deterministic first-message path in
    donna_runtime.brain.
    """
    if not user_id:
        return None
    try:
        import os
        from backend.auth.tokens import MAGIC_TTL_S, make_magic_token
    except Exception:
        logger.exception("mint_dashboard_url: import failed")
        return None
    base = (os.environ.get("DASHBOARD_BASE_URL") or "").rstrip("/")
    if not base:
        logger.warning("mint_dashboard_url: DASHBOARD_BASE_URL not set")
        return None
    try:
        token = make_magic_token(user_id)
    except Exception:
        logger.exception("mint_dashboard_url: token mint failed")
        return None
    url = f"{base}/auth/magic?t={token}"
    logger.info(
        "dashboard link issued: user_id=%s reason=%s ttl=%ds",
        user_id[:8], reason, MAGIC_TTL_S,
    )
    return url


@tool(
    "send_dashboard_link",
    (
        "Generate a fresh 5-minute magic link to the user's dashboard. "
        "Use when (a) the user explicitly asks ('send my dashboard', "
        "'open my home screen', 'where can i see all this'), or (b) a "
        "turn just produced something live and specific worth seeing "
        "there now — a loop closed, a streak ticked, an attention went "
        "live, a tracker hit a milestone, or the user just offloaded a "
        "concrete thing for the first time. Anchor your reply on the "
        "specific thing, then send the link. Include the URL verbatim in "
        "send_burst, valid 5 minutes. Onboarding: send within the first "
        "6-7 exchanges, ideally at the first moment something concrete "
        "lands there. Do NOT use on Day 1 (deterministic), on tiny "
        "acknowledgements, after every dashboard update, or as a "
        "generic status ping — that trains the user the link is noise."
    ),
    {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Short label for why the link was issued, e.g. "
                    "'first_message', 'user_request'. Logged for debugging; "
                    "not shown to the user."
                ),
            }
        },
        "required": ["reason"],
    },
)
async def send_dashboard_link(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("dashboard link: no user_id in scope.")
    reason = ""
    if isinstance(args, dict):
        reason = str(args.get("reason") or "").strip()
    reason = reason or "user_request"
    url = mint_dashboard_url(user_id, reason=reason)
    if url is None:
        return text_content("dashboard link: not available.")
    return text_content(f"link: {url} · valid 5 min · reason={reason}")


@tool(
    "send_login_otp",
    (
        "Generate a 6-digit login code the user can type on the dashboard's "
        "/auth/otp page. Use when the user explicitly asks for a login code "
        "('send me a code', 'i need to log in another way', 'i lost the "
        "link') or when the magic-link flow is broken on their end. Include "
        "the code verbatim in your send_burst reply and tell them it's "
        "valid for 10 minutes. After they verify, the dashboard session "
        "lasts 24 hours (longer than a magic-link session — that's the "
        "trade-off for typing a code). Do NOT use as the default login "
        "path; magic links are the primary surface. Returns the plaintext "
        "code (single-use, 10-min TTL)."
    ),
    {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Short label for why the OTP was issued, e.g. "
                    "'magic_link_failed', 'user_request'. Logged for "
                    "debugging; not shown to the user."
                ),
            }
        },
        "required": ["reason"],
    },
)
async def send_login_otp(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("login code: no user_id in scope.")
    reason = ""
    if isinstance(args, dict):
        reason = str(args.get("reason") or "").strip()
    reason = reason or "user_request"
    try:
        from backend.auth.otp import OTP_TTL_S, issue_otp
    except Exception:
        logger.exception("send_login_otp: import failed")
        return text_content("login code: subsystem unavailable.")
    try:
        code = await issue_otp(user_id)
    except Exception:
        logger.exception("send_login_otp: issue failed user_id=%s", user_id)
        return text_content("login code: issue failed.")
    logger.info(
        "send_login_otp issued: user_id=%s reason=%s ttl=%ds",
        user_id[:8], reason, OTP_TTL_S,
    )
    return text_content(
        f"code: {code} · valid 10 min · reason={reason}"
    )


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
    attend,
    list_attentions,
    cancel_attention,
    snooze_attention,
    accept_attention,
    check_calendar,
    image,
    web_search,
    agentic_web_search,
    research,
    connect_integration,
    check_integration_status,
    list_gmail_recent,
    search_gmail,
    read_gmail_thread,
    list_calendar,
    composio_search_tools,
    composio_execute_tool,
    update_dashboard,
    send_dashboard_link,
    send_login_otp,
    clear_pending_note,
    send_burst,  # terminator — must remain last
)
