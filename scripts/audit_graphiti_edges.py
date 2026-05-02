"""Audit Graphiti edges for meta-shape pollution.

Reads a sample of Graphiti edges for a user and classifies each fact as
either ``meta`` (subject/object are generic ``DONNA``/``USER``/``Donna``/
``the user``) or ``real`` (involves a specific person, project, or concept).

If meta > 30% the synthesis pipeline is poisoning the graph. Don't try to
fix the synthesis prompt here — surface the ratio and the source episodes
so the next operator can find the prompt and fix it deeper.

Usage:
    python -m scripts.audit_graphiti_edges
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

ARNAV_USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"

# Wide-coverage probe queries. Graphiti search ranks by relevance, so to
# approximate "random sample of edges" we issue many shallow queries and
# union the results.
PROBE_QUERIES = [
    "user",
    "donna",
    "tracking",
    "completed",
    "building",
    "project",
    "person",
    "friend",
    "family",
    "work",
    "study",
    "exam",
    "deadline",
    "habit",
    "recently",
    "today",
    "yesterday",
    "this week",
    "preference",
    "feeling",
]

_META_PATTERNS = (
    re.compile(r"\bDONNA\b", re.IGNORECASE),
    re.compile(r"\bthe\s+user\b", re.IGNORECASE),
    re.compile(r"^\s*USER\b", re.IGNORECASE),
)
# A fact is meta only if BOTH endpoints look generic. We approximate that
# with: the fact mentions DONNA/USER/the_user AND has no proper noun other
# than DONNA/USER (i.e. no capitalized token besides those).
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]{2,})\b")
_GENERIC_TOKENS = {"DONNA", "USER", "Donna", "User", "The"}


def classify(fact: str) -> str:
    if not fact:
        return "empty"
    has_meta_token = any(p.search(fact) for p in _META_PATTERNS)
    proper_nouns = {m.group(1) for m in _PROPER_NOUN_RE.finditer(fact)}
    proper_nouns -= _GENERIC_TOKENS
    if has_meta_token and not proper_nouns:
        return "meta"
    return "real"


async def main() -> int:
    from backend.memory.clients.graphiti import search_facts

    seen: dict[str, str] = {}
    for q in PROBE_QUERIES:
        try:
            facts = await search_facts(ARNAV_USER_ID, q, limit=12)
        except Exception as exc:
            print(f"  probe {q!r} failed: {exc}", file=sys.stderr)
            continue
        for f in facts:
            uuid = f.get("uuid") or f.get("fact")
            if uuid and uuid not in seen:
                seen[uuid] = f.get("fact") or ""

    if not seen:
        print("no edges returned — graphiti may be empty or unreachable")
        return 1

    counts = {"meta": 0, "real": 0, "empty": 0}
    meta_examples: list[str] = []
    real_examples: list[str] = []
    for fact in seen.values():
        kind = classify(fact)
        counts[kind] += 1
        if kind == "meta" and len(meta_examples) < 8:
            meta_examples.append(fact)
        elif kind == "real" and len(real_examples) < 5:
            real_examples.append(fact)

    total = sum(counts.values()) or 1
    meta_pct = counts["meta"] * 100.0 / total
    real_pct = counts["real"] * 100.0 / total

    print(f"\ngraphiti edge audit for user_id={ARNAV_USER_ID[:8]}...")
    print(f"unique edges sampled: {total}")
    print(f"  meta:  {counts['meta']} ({meta_pct:.1f}%)")
    print(f"  real:  {counts['real']} ({real_pct:.1f}%)")
    if counts["empty"]:
        print(f"  empty: {counts['empty']}")

    print("\nmeta examples:")
    for ex in meta_examples:
        print(f"  - {ex[:160]}")
    print("\nreal examples:")
    for ex in real_examples:
        print(f"  - {ex[:160]}")

    if meta_pct > 30:
        print(
            "\nWARNING: meta-edge ratio exceeds 30%. The graph synthesis prompt "
            "is producing self-referential edges that crowd out real entity "
            "relationships. Investigate the synthesis prompt that emits "
            "'DONNA is tracking ...' / 'the user is doing ...' shapes."
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
