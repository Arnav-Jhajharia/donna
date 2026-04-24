"""recall_episodic — search user's Supermemory episodes."""
from __future__ import annotations

from backend.memory.clients.supermemory import get_memory_client
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Search the user's stored conversational memories (episodes). "
    "Use for 'what did we say about X?' or 'remember when I mentioned Y'. "
    "DO NOT use for structured/countable data (use list_observations)."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "default": 8},
    },
    "required": ["query"],
}


@instrument_memory_op("supermemory")
async def recall_episodic(user_id: str, query: str, limit: int = 8) -> ToolResult:
    client = get_memory_client()
    if not client.available:
        return degraded("supermemory unavailable")
    hits = await client.search_with_graph(user_id, query, limit=limit)
    if not hits:
        return no_hits()
    return ok(
        [
            {"id": h.id, "content": h.content, "score": h.score, "updated_at": h.updated_at}
            for h in hits
        ]
    )
