from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.memory.synthesis.temporal_brief import (
    IMPLEMENTATIONS,
    build_all_temporal_briefs,
    build_stress_cases,
    collect_temporal_evidence,
    run_stress_test_implementations,
    score_brief,
    summarize_stress_results,
)
from backend.memory.synthesis.temporal_eval_dataset import (
    build_diverse_stress_cases,
    dataset_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress test Donna temporal situation brief implementations."
    )
    parser.add_argument("--user-id", help="Load real Postgres evidence for one user.")
    parser.add_argument("--now", help="ISO timestamp to use as current time.")
    parser.add_argument("--claude", action="store_true", help="Allow the Claude synthesis variant to call Anthropic.")
    parser.add_argument(
        "--dataset",
        choices=("basic", "diverse", "all"),
        default="basic",
        help="Synthetic dataset to run when --user-id is omitted.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a compact table.")
    parser.add_argument("--out", help="Optional path to write the full JSON report.")
    args = parser.parse_args()

    now = _parse_now(args.now)
    report = asyncio.run(_run(args.user_id, now=now, use_claude=args.claude, dataset=args.dataset))

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_table(report)


async def _run(
    user_id: str | None,
    *,
    now: datetime | None,
    use_claude: bool,
    dataset: str,
) -> dict[str, Any]:
    if user_id:
        evidence = await collect_temporal_evidence(user_id, now=now)
        briefs = await build_all_temporal_briefs(evidence, use_claude=use_claude)
        return {
            "mode": "real_user",
            "user_id": user_id,
            "use_claude": use_claude,
            "briefs": {
                name: {
                    "brief": brief.model_dump(),
                    "rendered": brief.render(),
                    "chars": len(brief.render()),
                }
                for name, brief in briefs.items()
            },
        }

    cases = _synthetic_cases(dataset)
    rows = await run_stress_test_implementations(cases, include_claude_fallback=True)
    if use_claude:
        # Synthetic cases have expected labels, so include a real Claude run only
        # as additional output. Heuristic scores remain apples-to-apples.
        for case in cases:
            briefs = await build_all_temporal_briefs(case.evidence, use_claude=True)
            brief = briefs["claude_synthesis"]
            rows.append(
                {
                    "case": case.id,
                    "implementation": "claude_synthesis_live",
                    "score": score_brief(brief, case),
                    "summary": brief.summary,
                    "current_status": brief.current_status,
                    "last_week": brief.last_week,
                    "this_week": brief.this_week,
                    "next_week": brief.next_week,
                    "open_loops": brief.open_loops,
                    "stale_or_uncertain": brief.stale_or_uncertain,
                    "chars": len(brief.render()),
                }
            )
    return {
        "mode": "synthetic",
        "dataset": dataset,
        "dataset_summary": dataset_summary(cases),
        "use_claude": use_claude,
        "implementations": [impl.value for impl in IMPLEMENTATIONS],
        "summary": summarize_stress_results(rows),
        "rows": rows,
    }


def _synthetic_cases(dataset: str):
    basic = build_stress_cases()
    if dataset == "basic":
        return basic
    diverse = build_diverse_stress_cases()
    if dataset == "diverse":
        return diverse
    return basic + diverse


def _parse_now(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _print_table(report: dict[str, Any]) -> None:
    if report["mode"] == "real_user":
        print(f"real user: {report['user_id']}  claude={report['use_claude']}")
        for name, payload in report["briefs"].items():
            print(f"\n## {name} ({payload['chars']} chars)")
            print(payload["rendered"])
        return

    dataset = report.get("dataset", "basic")
    summary = report.get("dataset_summary") or {}
    print(f"synthetic temporal brief stress test  dataset={dataset}  claude={report['use_claude']}")
    if summary:
        print(
            f"cases={summary['cases']} timezones={summary['timezone_count']} "
            f"overload={summary['overload_cases']}"
        )
    print("\nsummary")
    for row in report["summary"]:
        print(
            f"- {row['implementation']:<24} avg={row['average_score']:>5} "
            f"min={row['min_score']:>5} cases={row['cases']}"
        )
    print("\ncase details")
    for row in report["rows"]:
        print(
            f"- {row['case']:<22} {row['implementation']:<24} "
            f"score={row['score']['score']:>5} chars={row['chars']}"
        )


if __name__ == "__main__":
    main()
