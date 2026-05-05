from __future__ import annotations

import logging

from claude_agent_sdk import tool

from ..hooks import _CURRENT_USER_ID, _fire_memory_hooks
from ..langsmith_tracing import traceable
from ..tool_logic import read_tracker_result, text_content
from ._shared import _current_user_id, _render_payload, _result_text, _tool_text, disabled_tool

logger = logging.getLogger(__name__)


@disabled_tool(
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


@disabled_tool(
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


@disabled_tool(
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


@disabled_tool(
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


@disabled_tool(
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

