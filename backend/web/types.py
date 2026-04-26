"""Web retrieval DTOs — immutable.

Mirrors ``backend.memory.retrieval.types`` node-for-node so the two pipelines
share a mental model even when their backends differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WebHit:
    """Single external-web result.

    Treat ``score`` as the provider-native score (Exa relevance) and
    ``rerank_score`` as the fused / cross-encoder score after the rerank
    stage. ``retrieved_via`` records which expansion query fetched this hit
    so the trace can show source diversity.
    """

    url: str
    title: str
    snippet: str
    published_date: str | None = None
    author: str | None = None
    score: float = 0.0
    rerank_score: float = 0.0
    retrieved_via: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WebExpansion:
    rewritten_query: str
    neural_queries: list[str]
    keyword_queries: list[str]
    hypothetical: str | None


@dataclass(frozen=True)
class WebAnswer:
    """Output of the two-prompt synthesis stage.

    ``dissent`` holds the alternate synthesis when the two prompts disagreed
    meaningfully, so the caller can see the minority position. ``confidence``
    is the judge's 0..1 read on how well sources support the answer.
    """

    answer: str
    confidence: float
    sources: list[WebHit]
    dissent: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WebTrace:
    expansion: WebExpansion
    queries_fired: list[str]
    hits_by_query: dict[str, int]
    merged_count: int
    reranked_count: int
    timings_ms: dict[str, int]
    reranker_used: str
