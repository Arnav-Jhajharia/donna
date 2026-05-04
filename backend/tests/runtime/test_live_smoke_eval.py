"""Turn-level live-model smoke eval — fires real donna_turn() calls.

Gated behind DONNA_LIVE_EVAL=1 because:
- Requires ANTHROPIC_API_KEY
- Costs real money per fixture
- Slow (each fixture is a full BRAIN loop turn)

Run with:
    DONNA_LIVE_EVAL=1 python -m pytest tests/test_live_smoke_eval.py -v -s

CI integration:
    Run nightly or pre-merge, not on every commit.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("DONNA_LIVE_EVAL") != "1",
    reason="Set DONNA_LIVE_EVAL=1 to run live-model smoke eval.",
)

_MIN_PASS_RATIO = float(os.getenv("DONNA_LIVE_EVAL_MIN_RATIO") or "0.85")
_MIN_PASS_PER_CATEGORY = float(
    os.getenv("DONNA_LIVE_EVAL_MIN_CATEGORY_RATIO") or "0.75"
)


async def _ensure_sandbox_user(user_id: str) -> None:
    """Seed a sandbox user row so per-user FK writes resolve during the eval.

    Idempotent: ON CONFLICT (id) DO NOTHING. Phone is derived from user_id to
    stay unique across concurrent runs.
    """
    from db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, phone, name, timezone, facts, "
                "onboarding_complete, has_google, is_sandbox, created_at) "
                "VALUES (:id, :phone, :name, :tz, '{}'::jsonb, "
                "false, false, true, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": user_id,
                "phone": f"+live{abs(hash(user_id)) % 10_000_000_000:010d}",
                "name": "live eval sandbox",
                "tz": "Asia/Singapore",
            },
        )
        await session.commit()


def _pct(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def test_live_smoke_eval_overall_pass_ratio():
    """Hard gate: overall pass rate across all fixtures."""
    from donna_runtime.smoke_eval import run_all

    user_id = f"live-eval-{os.getenv('USER', 'anon')}"
    asyncio.run(_ensure_sandbox_user(user_id))
    results = asyncio.run(run_all(user_id))

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    ratio = _pct(passed, total)

    failure_summary = "\n".join(
        f"  [{r.fixture_id}] {r.category}: " + "; ".join(r.reasons)
        for r in results
        if not r.passed
    )
    assert ratio >= _MIN_PASS_RATIO, (
        f"Overall pass ratio {ratio:.0%} ({passed}/{total}) below "
        f"threshold {_MIN_PASS_RATIO:.0%}.\nFailures:\n{failure_summary}"
    )


def test_live_smoke_eval_per_category_pass_ratio():
    """Each category must pass the per-category minimum.

    Surfaces regressions that affect one dimension (e.g. voice drift)
    even when overall pass rate looks fine.
    """
    from donna_runtime.smoke_eval import run_all

    user_id = f"live-eval-cat-{os.getenv('USER', 'anon')}"
    asyncio.run(_ensure_sandbox_user(user_id))
    results = asyncio.run(run_all(user_id))

    by_category: dict[str, list] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    failures: list[str] = []
    for category, cat_results in by_category.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)
        cat_ratio = _pct(cat_passed, cat_total)
        if cat_ratio < _MIN_PASS_PER_CATEGORY:
            failures.append(
                f"  {category}: {cat_passed}/{cat_total} ({cat_ratio:.0%}) "
                f"< {_MIN_PASS_PER_CATEGORY:.0%}"
            )

    assert not failures, (
        "Per-category pass ratio below threshold:\n" + "\n".join(failures)
    )
