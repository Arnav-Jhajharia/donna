"""Multi-turn synthetic 3-day smoke eval.

Exercises cross-turn continuity: writes on day 1 must be recallable on
day 2 + 3. Time is injected; the arc replays in its own wall-clock.

Gated behind BOTH DONNA_LIVE_EVAL=1 (real model) and DONNA_E2E=1 (real
DB — continuity assertions need real writes/reads). If either is unset
the tests skip.

Run with:
    DONNA_LIVE_EVAL=1 DONNA_E2E=1 python -m pytest \\
        tests/test_multiturn_smoke_eval.py -v -s
"""
from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("DONNA_LIVE_EVAL") != "1" or os.getenv("DONNA_E2E") != "1",
    reason=(
        "Set DONNA_LIVE_EVAL=1 AND DONNA_E2E=1 to run multi-turn eval "
        "(needs live model + real DB for continuity assertions)."
    ),
)


def test_three_day_arc_turns_pass():
    """Each turn individually hits its per-turn assertions (tools, voice, widgets)."""
    from donna_runtime.smoke_eval_multiturn import THREE_DAY_ARC
    from donna_runtime.smoke_eval_multiturn_runner import (
        print_multiturn_report,
        run_multiturn_fixture,
    )

    result = asyncio.run(run_multiturn_fixture(THREE_DAY_ARC))
    print_multiturn_report(result)

    failures = [r for r in result.turn_results if not r.passed]
    summary = "\n".join(
        f"  [{r.turn_id}] {r.category}: " + "; ".join(r.reasons)
        for r in failures
    )
    assert not failures, (
        f"{len(failures)}/{result.total_turns} turns failed:\n{summary}"
    )


def test_three_day_arc_continuity():
    """Cross-turn memory: day-2 and day-3 recalls find day-1 writes."""
    from donna_runtime.smoke_eval_multiturn import THREE_DAY_ARC
    from donna_runtime.smoke_eval_multiturn_runner import (
        print_multiturn_report,
        run_multiturn_fixture,
    )

    result = asyncio.run(run_multiturn_fixture(THREE_DAY_ARC))
    print_multiturn_report(result)

    failures = [c for c in result.continuity_checks if not c["passed"]]
    summary = "\n".join(
        f"  {c['name']}: {c.get('reason')}\n     evidence: {c.get('evidence', '')}"
        for c in failures
    )
    assert not failures, (
        f"{len(failures)}/{len(result.continuity_checks)} continuity checks failed:\n"
        f"{summary}"
    )
