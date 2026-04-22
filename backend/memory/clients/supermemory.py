"""Typed Supermemory wrapper — ported from backend-v2/memory/client.py.

Degrades gracefully when SUPERMEMORY_API_KEY is missing: methods log a warning
and return empty results / empty ids rather than crashing.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any

from backend.config import get_settings, require

logger = logging.getLogger(__name__)

ENTITY_CONTEXT_TEMPLATE = (
    "{name} uses Donna, a personal AI assistant. "
    "Extract facts about their identity, occupation, location, living situation, "
    "preferences, routines, habits, relationships, plans, deadlines, "
    "health, finances, opinions, emotional state, and interests. "
    "Track recurring topics, disliked patterns, and action preferences. "
    "Note communication style and preferred depth of interaction."
)

DEFAULT_ENTITY_CONTEXT = ENTITY_CONTEXT_TEMPLATE.format(name="User")


def build_entity_context(name: str = "") -> str:
    if name:
        return ENTITY_CONTEXT_TEMPLATE.format(name=name)
    return DEFAULT_ENTITY_CONTEXT


@dataclasses.dataclass(frozen=True)
class MemoryResult:
    id: str
    content: str
    score: float
    updated_at: str
    metadata: dict = dataclasses.field(default_factory=dict)
    relations: list[dict] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class ChunkResult:
    content: str
    score: float
    doc_id: str = ""
    metadata: dict = dataclasses.field(default_factory=dict)


class MemoryClient:
    def __init__(self, _client: Any = None):
        if _client is not None:
            self._sm = _client
            return
        settings = get_settings()
        if not require("SUPERMEMORY_API_KEY", settings.supermemory_api_key):
            self._sm = None
            return
        try:
            from supermemory import AsyncSupermemory

            self._sm = AsyncSupermemory(api_key=settings.supermemory_api_key)
        except ImportError:
            logger.warning("supermemory SDK not installed")
            self._sm = None

    @property
    def available(self) -> bool:
        return self._sm is not None

    async def add_episode(
        self,
        user_id: str,
        content: str,
        message_type: str = "text",
        metadata: dict | None = None,
    ) -> str:
        if not self.available:
            return ""
        try:
            result = await self._sm.add(
                content=content,
                container_tag=user_id,
                metadata=metadata or {"message_type": message_type},
            )
            return getattr(result, "id", "") or ""
        except Exception:
            logger.exception("add_episode failed user=%s", user_id[:8])
            return ""

    async def search_with_graph(
        self, user_id: str, query: str, limit: int = 10
    ) -> list[MemoryResult]:
        if not self.available:
            return []
        try:
            result = await self._sm.search.memories(
                q=query,
                container_tag=user_id,
                limit=limit,
                search_mode="hybrid",
                include={"related_memories": True},
            )
            memories: list[MemoryResult] = []
            for r in getattr(result, "results", []) or []:
                content = (
                    getattr(r, "chunk", "")
                    or getattr(r, "memory", "")
                    or getattr(r, "content", "")
                )
                score = float(getattr(r, "similarity", None) or getattr(r, "score", 0.0))
                relations = []
                for rel in getattr(r, "related_memories", []) or []:
                    relations.append(
                        {
                            "relation": getattr(rel, "type", "related"),
                            "memory": getattr(rel, "chunk", "")
                            or getattr(rel, "content", ""),
                        }
                    )
                memories.append(
                    MemoryResult(
                        id=getattr(r, "id", ""),
                        content=content,
                        score=score,
                        updated_at=str(getattr(r, "updated_at", "")),
                        metadata=dict(r.metadata) if getattr(r, "metadata", None) else {},
                        relations=relations,
                    )
                )
            return memories
        except Exception:
            logger.exception("search_with_graph failed user=%s", user_id[:8])
            return []

    async def search_document_chunks(
        self,
        user_id: str,
        query: str,
        doc_id: str | None = None,
        limit: int = 10,
    ) -> list[ChunkResult]:
        if not self.available:
            return []
        try:
            kwargs: dict[str, Any] = {
                "q": query,
                "container_tags": [user_id],
                "limit": limit,
                "rerank": True,
                "include_summary": True,
            }
            if doc_id:
                kwargs["doc_id"] = doc_id
            result = await self._sm.search.documents(**kwargs)
            chunks: list[ChunkResult] = []
            for doc in getattr(result, "results", []) or []:
                doc_meta: dict = {}
                for attr in ("metadata", "custom_id", "id", "title"):
                    val = getattr(doc, attr, None)
                    if val is not None:
                        doc_meta[attr] = val
                for chunk in getattr(doc, "chunks", []) or []:
                    chunks.append(
                        ChunkResult(
                            content=getattr(chunk, "content", "")
                            or getattr(chunk, "chunk", ""),
                            score=float(getattr(chunk, "score", 0.0)),
                            doc_id=doc_meta.get("id", ""),
                            metadata=doc_meta,
                        )
                    )
            return chunks
        except Exception:
            logger.exception("search_document_chunks failed user=%s", user_id[:8])
            return []


def _sanitize_metadata(meta: dict) -> dict:
    clean: dict = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, float, int, bool)):
            clean[k] = v
        elif isinstance(v, list):
            clean[k] = [str(i) for i in v]
        elif isinstance(v, dict):
            clean[k] = json.dumps(v)
        else:
            clean[k] = str(v)
    return clean


_client_singleton: MemoryClient | None = None


def get_memory_client() -> MemoryClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = MemoryClient()
    return _client_singleton
