"""PostToolUse hooks (spec §6).

All four hooks run after a `send_burst` turn. The runtime wraps each in
`asyncio.create_task(...)` so they never block response delivery.

Expected trace context shape:
    {
        "user_id": str,
        "inbound": str,                 # last user message
        "outbound": list[str],          # assistant messages delivered this turn
        "tool_names": list[str],        # tools invoked during the turn
        "terminator": "send_burst",
        "user_facts": dict,             # optional; for fact-extraction context
    }
"""
from __future__ import annotations

from backend.memory.hooks import (
    extract_user_facts,
    ingest_to_graph,
    record_episode,
    save_chat_messages,
)

ALL_HOOKS = (
    save_chat_messages.run,
    record_episode.run,
    ingest_to_graph.run,
    extract_user_facts.run,
)
