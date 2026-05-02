"""Smoke-test recall against Arnav's live profile.

Runs a battery of queries through smart_recall (the unified pipeline:
expand -> fanout -> RRF rerank) and prints the per-lane hit counts +
top results so we can see what recall actually surfaces today.

Usage:
    python -m scripts.recall_smoke_arnav

Reads DATABASE_URL, SUPERMEMORY_API_KEY, FALKORDB_* from .env.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

# Load .env so the script works from a bare shell.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

ARNAV_USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"

QUERIES = [
    "what's pulling on me this week",
    "deploy",
    "saurabh",
    "what did i tell you about maya",
    "did i drink water today",
    "open loops",
    "what am i tracking",
    "what's on my plate today",
    "exam prep",
    "code review",
]


async def main() -> int:
    from backend.memory.retrieval.pipeline import run_retrieval

    print(f"\nrecall smoke for user_id={ARNAV_USER_ID[:8]}...\n")
    print(f"{'query':<45} {'total':<6} {'lanes':<40}")
    print("-" * 95)

    for q in QUERIES:
        try:
            results, trace = await run_retrieval(
                user_id=ARNAV_USER_ID, message=q, top_k=8
            )
        except Exception as exc:
            print(f"{q[:43]!r:<45} ERROR: {type(exc).__name__}: {exc}")
            continue
        lanes = Counter(r.source for r in results)
        lane_str = ", ".join(f"{k}:{v}" for k, v in lanes.most_common())
        print(f"{q[:43]!r:<45} {len(results):<6} {lane_str:<40}")
        if results:
            top = results[0]
            preview = (top.content or "")[:120].replace("\n", " ")
            print(f"  top: [{top.source}] score={top.score:.2f} {preview}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
