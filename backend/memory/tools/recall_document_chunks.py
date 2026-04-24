"""recall_document_chunks — doc Q&A via Supermemory chunks."""
from __future__ import annotations

from backend.memory.clients.supermemory import get_memory_client
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Search chunks of the user's uploaded documents. Use for doc Q&A "
    "('what does the contract say about X?'). Optional doc_id scopes to one doc."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "doc_id": {"type": "string"},
        "limit": {"type": "integer", "default": 8},
    },
    "required": ["query"],
}


@instrument_memory_op("supermemory.docs")
async def recall_document_chunks(
    user_id: str, query: str, doc_id: str | None = None, limit: int = 8
) -> ToolResult:
    client = get_memory_client()
    if not client.available:
        return degraded("supermemory unavailable")
    chunks = await client.search_document_chunks(user_id, query, doc_id=doc_id, limit=limit)
    if not chunks:
        return no_hits()
    return ok(
        [
            {"doc_id": c.doc_id, "content": c.content, "score": c.score, "meta": c.metadata}
            for c in chunks
        ]
    )
