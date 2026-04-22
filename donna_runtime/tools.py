from __future__ import annotations

from claude_agent_sdk import tool

from .hooks import _CURRENT_TRACE, _CURRENT_USER_ID, _fire_memory_hooks
from .langsmith_tracing import traceable
from .tool_logic import (
    read_tracker_result,
    recall_episodic_result,
    send_burst_result,
    stay_silent_result,
    text_content,
)


@tool(
    "recall_episodic",
    "Search episodic memory for past-conversation snippets not in the Living Profile. "
    "Returns up to 5 dated snippets. Skip if Living Profile already has the answer.",
    {"query": str},
)
@traceable(name="donna.tool.recall_episodic", run_type="tool")
async def recall_episodic(args):
    return await recall_episodic_result(args)


@tool(
    "read_tracker",
    "Read-only tracker lookup by observation type (e.g. 'expense', 'mood'). "
    "Returns JSON list of recent observations.",
    {"name": str},
)
@traceable(name="donna.tool.read_tracker", run_type="tool")
async def read_tracker(args):
    return await read_tracker_result(args)


@tool(
    "recall_graph",
    "Search the user's knowledge graph for relational facts (people, decisions, "
    "commitments). Returns up to 10 facts with timestamps.",
    {"query": str},
)
@traceable(name="donna.tool.recall_graph", run_type="tool")
async def recall_graph(args):
    from backend.memory.tools.recall_graph import recall_graph as _recall_graph

    user_id = _CURRENT_USER_ID.get()
    query = str(args.get("query", "")).strip()
    if not user_id or not query:
        return text_content("No graph hits.")
    res = await _recall_graph(user_id=user_id, query=query, limit=10)
    payload = res.get("payload") or []
    if not payload:
        return text_content("No graph hits.")
    lines = [f"- {f.get('fact', '')}" for f in payload if isinstance(f, dict)]
    return text_content("\n".join(lines) or "No graph hits.")


@tool(
    "smart_recall",
    "Adaptive recall across episodic, graph, and document memory. Use when you "
    "need the best-ranked hits without choosing a specific source.",
    {"message": str},
)
@traceable(name="donna.tool.smart_recall", run_type="tool")
async def smart_recall(args):
    from backend.memory.tools.smart_recall import smart_recall as _smart_recall

    user_id = _CURRENT_USER_ID.get()
    message = str(args.get("message", "")).strip()
    if not user_id or not message:
        return text_content("No hits.")
    res = await _smart_recall(user_id=user_id, message=message, top_k=8)
    payload = res.get("payload") or []
    if not payload:
        return text_content("No hits.")
    lines = []
    for item in payload[:8]:
        if isinstance(item, dict):
            lines.append(f"- {item.get('content') or item.get('fact') or item}")
    return text_content("\n".join(lines) or "No hits.")


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


@tool(
    "stay_silent",
    "TERMINATOR. Choose not to respond (ambient chatter, not directed at Donna, etc). "
    "Log a short reason.",
    {"reason": str},
)
@traceable(name="donna.tool.stay_silent", run_type="tool")
async def stay_silent(args):
    return await stay_silent_result(args)


DONNA_TOOLS = (
    recall_episodic,
    read_tracker,
    recall_graph,
    smart_recall,
    send_burst,
    stay_silent,
)
