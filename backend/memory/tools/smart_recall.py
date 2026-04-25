"""smart_recall — wraps retrieval pipeline (expansion -> fanout -> rerank)."""
from __future__ import annotations

from backend.memory.retrieval.pipeline import run_retrieval
from backend.memory.tools._shape import ToolResult, no_hits, ok
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Fuzzy recall across episodes + knowledge graph when you don't know where to look. "
    "Runs query expansion + parallel fanout + RRF rerank. Prefer specific recall_* tools "
    "when you know the right backend."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "top_k": {"type": "integer", "default": 8},
    },
    "required": ["message"],
}


@instrument_memory_op("pipeline")
async def smart_recall(user_id: str, message: str, top_k: int = 8) -> ToolResult:
    results, trace = await run_retrieval(user_id=user_id, message=message, top_k=top_k)
    if not results:
        return no_hits()
    return ok(
        [
            {
                "id": r.id,
                "source": r.source,
                "content": r.content,
                "score": r.score,
                "rerank_score": r.rerank_score,
            }
            for r in results
        ]
    )
