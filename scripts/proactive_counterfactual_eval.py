"""Counterfactual eval — Phase 1 counterfactual input-build report.

Reads ``proactive_dispatch_telemetry`` rows from the last N days and
prints:
  - Total events dispatched
  - Counterfactual input-build success rate (input_built vs
    input_failed) — proves the Tier 3 input contract is wiring cleanly
  - Per-speech-act breakdown
  - Per-source breakdown
  - elapsed_ms p50 / p95 for the input-build path
  - Top error types when input_failed

Phase 2 will extend this with ship/skip ratios once the Tier 3 LLM
call wires up.

Run:
    python -m scripts.proactive_counterfactual_eval --days 7
    python -m scripts.proactive_counterfactual_eval --user user_xxx
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select


async def _load_rows(*, days: int, user_id: str | None) -> list[Any]:
    from backend.db.session import async_session
    from db.models import ProactiveDispatchTelemetry

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        q = select(ProactiveDispatchTelemetry).where(
            ProactiveDispatchTelemetry.event_at >= cutoff.replace(tzinfo=None)
        )
        if user_id:
            q = q.where(ProactiveDispatchTelemetry.user_id == user_id)
        q = q.order_by(ProactiveDispatchTelemetry.event_at.desc())
        rows = (await session.execute(q)).scalars().all()
    return list(rows)


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(len(s) * pct) - 1))
    return s[idx]


def _summarize(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    legacy_ships = sum(
        1 for r in rows if (r.counterfactual_legacy_outbound_count or 0) > 0
    )

    # Phase 2A outcomes
    outcomes = ("ship", "skip", "reshape", "kill", "error", "no_terminator",
                "input_built", "input_failed")
    counts = {
        outcome: sum(
            1 for r in rows
            if r.counterfactual_fat_contract_outcome == outcome
        )
        for outcome in outcomes
    }

    # Per-speech-act breakdown
    by_act: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "n": 0, "legacy_ships": 0,
            **{o: 0 for o in outcomes},
        }
    )
    for r in rows:
        act = r.speech_act or "unknown"
        by_act[act]["n"] += 1
        if (r.counterfactual_legacy_outbound_count or 0) > 0:
            by_act[act]["legacy_ships"] += 1
        outcome = r.counterfactual_fat_contract_outcome
        if outcome in by_act[act]:
            by_act[act][outcome] += 1

    # Per-source breakdown
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, **{o: 0 for o in outcomes}}
    )
    for r in rows:
        src = r.source or "unknown"
        by_source[src]["n"] += 1
        outcome = r.counterfactual_fat_contract_outcome
        if outcome in by_source[src]:
            by_source[src][outcome] += 1

    elapsed = [
        r.counterfactual_fat_contract_elapsed_ms
        for r in rows
        if r.counterfactual_fat_contract_elapsed_ms is not None
    ]
    p50 = _percentile(elapsed, 0.50)
    p95 = _percentile(elapsed, 0.95)

    errors = Counter()
    for r in rows:
        if (
            r.counterfactual_fat_contract_outcome == "error"
            and r.counterfactual_fat_contract_error
        ):
            err_type = r.counterfactual_fat_contract_error.split(":", 1)[0]
            errors[err_type] += 1

    return {
        "total": total,
        "legacy_ships": legacy_ships,
        **counts,
        "by_speech_act": dict(by_act),
        "by_source": dict(by_source),
        "elapsed_ms_p50": p50,
        "elapsed_ms_p95": p95,
        "top_errors": errors.most_common(5),
    }


def _print_report(summary: dict[str, Any], days: int) -> None:
    total = summary["total"]
    print(f"=== proactive counterfactual eval — last {days} days ===\n")
    print(f"total events dispatched:  {total}")
    print(f"  legacy ships:           {summary['legacy_ships']}")
    print(f"  ship (tier 3):          {summary['ship']}")
    print(f"  skip (tier 3):          {summary['skip']}")
    print(f"  reshape (tier 3):       {summary['reshape']}")
    print(f"  kill (tier 3):          {summary['kill']}")
    print(f"  error (tier 3):         {summary['error']}")
    print(f"  no_terminator:          {summary['no_terminator']}")
    print(f"  input_built (legacy):   {summary['input_built']}")
    print(f"  input_failed (legacy):  {summary['input_failed']}")
    print(f"  elapsed_ms p50 / p95:   {summary['elapsed_ms_p50']} / {summary['elapsed_ms_p95']}")
    print()

    if summary["by_speech_act"]:
        print("per speech_act:")
        for act, stats in sorted(summary["by_speech_act"].items()):
            print(
                f"  {act:20} n={stats['n']:>4}  "
                f"ship={stats['ship']:>3}  "
                f"skip={stats['skip']:>3}  "
                f"reshape={stats['reshape']:>2}  "
                f"kill={stats['kill']:>2}  "
                f"err={stats['error']:>2}"
            )
        print()

    if summary["by_source"]:
        print("per source:")
        for src, stats in sorted(summary["by_source"].items()):
            print(
                f"  {src:20} n={stats['n']:>4}  "
                f"ship={stats['ship']:>3}  "
                f"skip={stats['skip']:>3}  "
                f"err={stats['error']:>2}"
            )
        print()

    if summary["top_errors"]:
        print("top error types (Tier 3 SDK exceptions):")
        for err_type, count in summary["top_errors"]:
            print(f"  {err_type}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Counterfactual eval for proactive brain Phase 1.",
    )
    parser.add_argument(
        "--days", type=int, default=7, help="window in days (default 7)",
    )
    parser.add_argument(
        "--user", type=str, default=None, help="filter to one user_id",
    )
    args = parser.parse_args()

    async def _run() -> dict[str, Any]:
        rows = await _load_rows(days=args.days, user_id=args.user)
        return _summarize(rows)

    summary = asyncio.run(_run())
    _print_report(summary, days=args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
