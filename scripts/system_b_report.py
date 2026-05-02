"""Dump a full System B report to a markdown file.

Like ``system_b_demo.py`` but writes a clean .md report you can read
later — every query, every item, full URL, full snippet, grouped by
angle. Use this to evaluate query/result quality before wiring
System B into the production poller.

Usage:
    python scripts/system_b_report.py <user_id>
    python scripts/system_b_report.py <user_id> --out path/to/report.md
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id")
    parser.add_argument("--out", default=None,
                        help="path to write report (default: scripts/_out/system_b_<ts>.md)")
    parser.add_argument("--max-queries", type=int, default=12)
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else (
        ROOT / "scripts" / "_out" / f"system_b_{_ts_now()}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from backend.web.proactive.system_b.query_gen import (
        generate_ambitious_queries,
    )
    from backend.web.proactive.system_b.fetcher import fetch_for_queries

    print(f"generating queries for user {args.user_id[:12]}...")
    queries = await generate_ambitious_queries(
        args.user_id, max_queries=args.max_queries
    )
    print(f"got {len(queries)} queries; fetching...")
    items, summary = await fetch_for_queries(queries, user_id=args.user_id)
    print(f"got {len(items)} deduped items")

    by_query: dict[str, list] = defaultdict(list)
    for it in items:
        by_query[it.source_query].append(it)

    lines: list[str] = []
    lines.append(f"# System B Report — {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append(f"**User:** `{args.user_id}`")
    lines.append("")
    lines.append("## Cost summary")
    lines.append("")
    lines.append(f"- queries generated: {summary.queries_run}")
    lines.append(f"- /search calls:     {summary.search_calls}  (~{summary.search_calls * 5} credits)")
    lines.append(f"- /findSimilar:      {summary.similar_calls}  (~{summary.similar_calls * 5} credits)")
    lines.append(f"- raw items:         {summary.raw_items}")
    lines.append(f"- after dedup:       {summary.deduped_items}")
    lines.append(f"- **total cost:**    ~{(summary.search_calls + summary.similar_calls) * 5} credits / cycle")
    lines.append("")

    lines.append("## Queries by angle")
    lines.append("")
    by_angle: dict[str, list] = defaultdict(list)
    for q in queries:
        by_angle[q.angle].append(q)
    for angle in sorted(by_angle):
        lines.append(f"### {angle}")
        lines.append("")
        for q in by_angle[angle]:
            sim = " · +similar" if q.expand_with_similar else ""
            lines.append(f"- **`[{q.cadence}{sim}]`** {q.text}")
            if q.ties_to:
                lines.append(f"  - *ties_to:* {q.ties_to}")
        lines.append("")

    lines.append("## Results per query")
    lines.append("")
    for q in queries:
        q_items = by_query.get(q.text, [])
        sim = " · +similar" if q.expand_with_similar else ""
        lines.append(f"### `[{q.cadence}{sim}|{q.angle}]` {q.text}")
        lines.append("")
        if q.ties_to:
            lines.append(f"*ties_to:* {q.ties_to}")
            lines.append("")
        if not q_items:
            lines.append("_no results_")
            lines.append("")
            continue
        for it in q_items:
            mark = "🔗" if it.via_similar else "➤ "
            pub = f" *(published {it.published_date[:10]})*" if it.published_date else ""
            lines.append(f"- {mark} **{it.title}**{pub}")
            lines.append(f"  - {it.url}")
            if it.snippet:
                snip = it.snippet.replace("\n", " ").strip()
                lines.append(f"  - _{snip[:300]}_")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport written to: {out_path}")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
