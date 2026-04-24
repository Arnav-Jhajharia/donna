"""Retrieval DTOs — immutable."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Source = Literal[
    "supermemory",
    "graphiti",
    "observations",
    "open_loops",
    "situation_brief",
]


@dataclass(frozen=True)
class RetrievalResult:
    id: str
    source: Source
    content: str
    score: float
    rerank_score: float = 0.0
    retrieved_via: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Expansion:
    rewritten_query: str
    facets: list[str]
    hypothetical: str | None


@dataclass(frozen=True)
class RetrievalTrace:
    expansion: Expansion
    queries_fired: list[str]
    raw_hits_by_query: dict[str, int]
    raw_hits_by_source: dict[str, int]
    merged_count: int
    reranked_count: int
    timings_ms: dict[str, int]
