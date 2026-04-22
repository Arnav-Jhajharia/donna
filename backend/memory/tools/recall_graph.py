"""recall_graph — search Graphiti knowledge graph for entity/relationship facts."""
from __future__ import annotations

from backend.memory.clients.graphiti import search_facts
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok

DESCRIPTION = (
    "Search the user's knowledge graph for facts about people, places, and entities. "
    "Use for 'what do I know about X?' where X is a person/entity. "
    "DO NOT use for recent episodic content (use recall_episodic)."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "default": 8},
    },
    "required": ["query"],
}


async def recall_graph(user_id: str, query: str, limit: int = 8) -> ToolResult:
    try:
        facts = await search_facts(user_id, query, limit=limit)
    except Exception:
        return degraded("graphiti error")
    if not facts:
        return no_hits()
    return ok(facts)
