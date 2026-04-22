"""Few-shot retrieval over gold examples.

Pure-Python TF-IDF cosine retrieval — no sklearn/numpy dependency. Voyage
path activates when VOYAGE_API_KEY is set (deferred; stub raises so callers
can fall back cleanly). Vectors are cached in-process.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from donna.attention.examples.gold_specs import GOLD_EXAMPLES, GoldExample


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _example_corpus_text(ex: GoldExample) -> str:
    parts = list(ex.intent_examples) + list(ex.context_signals)
    parts.append(ex.spec.title)
    parts.append(ex.spec.description)
    parts.append(ex.spec.subject.name)
    parts.append(ex.spec.card.value)
    parts.extend(tag.value for tag in ex.spec.domain_tags)
    return " ".join(parts)


@dataclass(frozen=True)
class _TfIdfIndex:
    docs: tuple[dict[str, float], ...]
    examples: tuple[GoldExample, ...]


@lru_cache(maxsize=1)
def _build_index() -> _TfIdfIndex:
    examples = GOLD_EXAMPLES
    tokenized = [_tokenize(_example_corpus_text(e)) for e in examples]
    # Document frequency
    df: dict[str, int] = {}
    for toks in tokenized:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n_docs = len(tokenized)
    # TF-IDF weight per doc
    docs: list[dict[str, float]] = []
    for toks in tokenized:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        total = max(len(toks), 1)
        weights: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1.0
            weights[term] = (count / total) * idf
        docs.append(weights)
    return _TfIdfIndex(docs=tuple(docs), examples=examples)


def _query_vector(tokens: list[str], df: dict[str, int], n_docs: int) -> dict[str, float]:
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    total = max(len(tokens), 1)
    weights: dict[str, float] = {}
    for term, count in tf.items():
        idf = math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1.0
        weights[term] = (count / total) * idf
    return weights


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = 0.0
    for term, wa in a.items():
        wb = b.get(term)
        if wb is not None:
            dot += wa * wb
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(frozen=True)
class Retrieved:
    example: GoldExample
    score: float


def retrieve_top_k(query: str, k: int = 3) -> list[Retrieved]:
    """Return top-k gold examples most relevant to the query string."""
    if k <= 0:
        return []
    index = _build_index()
    # Reconstruct df from the index for query vectorization
    df: dict[str, int] = {}
    for doc in index.docs:
        for t in doc:
            df[t] = df.get(t, 0) + 1
    q_vec = _query_vector(_tokenize(query), df, len(index.docs))
    scored = [
        Retrieved(example=ex, score=_cosine(q_vec, doc))
        for ex, doc in zip(index.examples, index.docs)
    ]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:k]
