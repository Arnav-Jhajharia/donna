"""Boost retrieval hits whose content mentions any active attention subject.

Donna's attention subsystem tracks what the user is actively watching. When
recalling memory, hits that touch those subjects are more likely to be
load-bearing, so we nudge their rerank score.

Boost is multiplicative and capped so it cannot invert the base ranking for
unrelated hits — it only lifts ties and near-ties.
"""
from __future__ import annotations

from typing import Iterable

from backend.memory.retrieval.types import RetrievalResult

_BOOST_FACTOR = 1.35
_MAX_BOOSTS = 3


def _extract_subjects(attentions: Iterable[object]) -> list[str]:
    subjects: list[str] = []
    for a in attentions:
        spec = getattr(a, "spec", a)
        subject = getattr(spec, "subject", None)
        name = getattr(subject, "name", None) if subject is not None else None
        if isinstance(name, str):
            name = name.strip().lower()
            if name:
                subjects.append(name)
    return subjects


def apply_attention_boost(
    hits: list[RetrievalResult],
    attentions: Iterable[object],
) -> list[RetrievalResult]:
    """Return a new list of hits with rerank_score boosted for attention matches.

    Match rule: case-insensitive substring on content or metadata.title.
    A given hit is boosted at most once, regardless of how many subjects match.
    """
    subjects = _extract_subjects(attentions)
    if not subjects or not hits:
        return list(hits)

    def matches(hit: RetrievalResult) -> bool:
        haystack_parts: list[str] = []
        if isinstance(hit.content, str):
            haystack_parts.append(hit.content.lower())
        md = getattr(hit, "metadata", None)
        if isinstance(md, dict):
            title = md.get("title")
            if isinstance(title, str):
                haystack_parts.append(title.lower())
        haystack = " ".join(haystack_parts)
        return any(s in haystack for s in subjects)

    out: list[RetrievalResult] = []
    boosts_applied = 0
    for h in hits:
        if boosts_applied < _MAX_BOOSTS and matches(h):
            out.append(
                RetrievalResult(
                    id=h.id,
                    source=h.source,
                    content=h.content,
                    score=h.score,
                    rerank_score=(h.rerank_score or h.score) * _BOOST_FACTOR,
                    retrieved_via=h.retrieved_via,
                    metadata=h.metadata,
                )
            )
            boosts_applied += 1
        else:
            out.append(h)

    out.sort(key=lambda r: r.rerank_score or r.score, reverse=True)
    return out
