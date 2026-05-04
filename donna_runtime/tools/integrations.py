from __future__ import annotations

from claude_agent_sdk import tool

from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id, _tool_text

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

