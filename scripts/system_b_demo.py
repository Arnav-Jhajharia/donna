"""Demo System B end-to-end against a real user's Living Profile.

Stages:
  1. Generate ambitious queries from the user's LP (Haiku).
  2. Print the queries grouped by angle so you can sanity-check quality.
  3. Run the webset-emulating fetcher (multi /search + /findSimilar +
     dedup against historical signals).
  4. Print fetched items grouped by source query.

This is a READ-ONLY operation aside from the Haiku/Exa calls. It does
NOT enqueue signals into proactive_signals or kick the drain trigger.
You can run it dry as many times as you want; each run costs:
  - 1 Haiku call for query gen (~few cents)
  - ~12 /search + ~6 /findSimilar (~90 Exa credits = ~$0.10)

Usage:
    python scripts/system_b_demo.py <user_id>
    python scripts/system_b_demo.py <user_id> --no-fetch  # query gen only
    python scripts/system_b_demo.py <user_id> --skip-dedup  # show all
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _hr() -> None:
    print("─" * 78)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo System B (ambitious query gen + webset emulation)."
    )
    parser.add_argument("user_id", help="user_id to read LP from")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the fetch stage (queries only)")
    parser.add_argument("--skip-dedup", action="store_true",
                        help="show all fetched items, including ones in historical signals")
    parser.add_argument("--max-queries", type=int, default=12)
    args = parser.parse_args()

    from backend.web.proactive.system_b.query_gen import (
        generate_ambitious_queries,
    )
    from backend.web.proactive.system_b.fetcher import fetch_for_queries

    print()
    _hr()
    print(f"  STAGE 1: AMBITIOUS QUERY GENERATION  (user={args.user_id[:12]}...)")
    _hr()

    queries = await generate_ambitious_queries(
        args.user_id, max_queries=args.max_queries
    )
    print(f"  generated {len(queries)} queries")
    print()

    by_angle: dict[str, list] = defaultdict(list)
    for q in queries:
        by_angle[q.angle].append(q)

    for angle in sorted(by_angle.keys()):
        items = by_angle[angle]
        print(f"  ── {angle.upper()} ({len(items)})")
        for q in items:
            sim = " +similar" if q.expand_with_similar else ""
            print(f"     [{q.cadence:8s}{sim:9s}] {q.text}")
            if q.ties_to:
                print(f"                          ties_to: {q.ties_to[:80]}")
        print()

    if args.no_fetch:
        return

    if not queries:
        print("  no queries to fetch; exiting.")
        return

    _hr()
    print("  STAGE 2: WEBSET-EMULATING FETCH  (search + findSimilar + dedup)")
    _hr()

    items, summary = await fetch_for_queries(
        queries, user_id=args.user_id, skip_dedup=args.skip_dedup,
    )
    print(f"  queries run:    {summary.queries_run}")
    print(f"  /search calls:  {summary.search_calls}  (~{summary.search_calls * 5} credits)")
    print(f"  /findSimilar:   {summary.similar_calls}  (~{summary.similar_calls * 5} credits)")
    print(f"  raw items:      {summary.raw_items}")
    print(f"  after dedup:    {summary.deduped_items}")
    print(
        f"  estimated cost: ~{(summary.search_calls + summary.similar_calls) * 5} "
        "credits per cycle"
    )
    print()

    by_query: dict[str, list] = defaultdict(list)
    for it in items:
        by_query[it.source_query].append(it)

    for q_text, q_items in sorted(by_query.items()):
        # Find the cadence/angle for this query
        match = next((q for q in queries if q.text == q_text), None)
        cad = match.cadence if match else "?"
        angle = match.angle if match else "?"
        print(f"  ── [{cad}|{angle}] {q_text[:80]}")
        for it in q_items:
            mark = " (~)" if it.via_similar else "    "
            print(f"     {mark} {it.title[:75]}")
            print(f"          {it.url[:90]}")
            if it.published_date:
                print(f"          published: {it.published_date[:10]}")
        print()


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
