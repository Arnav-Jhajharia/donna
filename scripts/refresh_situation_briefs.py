from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.memory.jobs.temporal_refresh import refresh_active_user_briefs
from backend.memory.synthesis.temporal_brief import BriefImplementation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh stored temporal situation briefs for active Donna users."
    )
    parser.add_argument("--active-days", type=int, default=14)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-sandbox", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude", action="store_true", help="Allow Claude synthesis.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--implementation",
        default=BriefImplementation.WINDOWED_TIMELINE.value,
        choices=[item.value for item in BriefImplementation],
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(
        refresh_active_user_briefs(
            active_within_days=args.active_days,
            limit=args.limit,
            include_sandbox=args.include_sandbox,
            dry_run=args.dry_run,
            implementation=args.implementation,
            use_claude=args.claude,
            concurrency=args.concurrency,
        )
    )

    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(
        "temporal brief refresh "
        f"dry_run={payload['dry_run']} selected={payload['selected']} "
        f"refreshed={payload['refreshed']} failed={payload['failed']} "
        f"skipped={payload['skipped']}"
    )
    for outcome in payload["outcomes"][:20]:
        evidence = outcome.get("evidence_used") or {}
        print(
            f"- {outcome['user_id']} {outcome['status']} "
            f"{outcome.get('implementation') or ''} evidence={evidence}"
        )
    if len(payload["outcomes"]) > 20:
        print(f"... {len(payload['outcomes']) - 20} more")


if __name__ == "__main__":
    main()
