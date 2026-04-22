"""Deterministic evals for the proactive loop.

Run: `python -m donna.attention.evals.eval_proactive`

Covers the non-LLM parameters from the testing spec:
  #3 shadow-tick latency
  #5 promotion decay (archive ≥ 50% on empty fixtures)
  #6 duplicate suppression
  #7 offer idempotency

The LLM-gated parameters (#1 proposer precision, #2 recall, #4 hit
calibration, #8 retry rate, #9 cost, #10 conversion time) need labeled
gold data and live Haiku calls; they are tracked in `gold_candidates.jsonl`
and exercised by a separate driver (out of scope here — see the report
`PROACTIVE_EVAL_REPORT.md`).
"""
from __future__ import annotations

import asyncio
import csv
import io
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.promote import accept_offer, reject_offer, run_shadow_cycle
from donna.attention.propose import (
    CalendarRecurrenceProposer,
    CandidateIntent,
    propose_and_shadow,
)
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    ShadowState,
)
from donna.attention.store import AttentionStore


# -- Test harness utilities --------------------------------------------------


@dataclass
class EvalResult:
    name: str
    target: str
    measured: str
    passed: bool
    notes: str = ""


def _fresh_store(tmpdir: Path) -> AttentionStore:
    return AttentionStore(path=tmpdir / f"store_{uuid4()}.json")


def _seed_shadow(store: AttentionStore, n: int, *, max_ticks: int = 3) -> None:
    poke = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    for _ in range(n):
        store.save(
            Attention(
                user_id=uuid4(),
                spec=poke,
                origin=AttentionOrigin.SHADOW_INFERRED,
                status=AttentionStatus.SHADOW,
                created_at=datetime.now(timezone.utc),
                shadow_state=ShadowState(max_ticks=max_ticks),
            )
        )


# -- Individual evals --------------------------------------------------------


def eval_shadow_tick_latency(tmpdir: Path) -> EvalResult:
    """#3: 10 shadow attentions tick in < 5s."""
    store = _fresh_store(tmpdir)
    _seed_shadow(store, 10)
    t0 = time.perf_counter()
    run_shadow_cycle(store=store)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return EvalResult(
        name="shadow_tick_latency",
        target="< 5000 ms for 10 shadows",
        measured=f"{elapsed_ms:.1f} ms",
        passed=elapsed_ms < 5000,
    )


def eval_promotion_decay(tmpdir: Path) -> EvalResult:
    """#5: when signal is absent, ≥ 50% of shadows archive (don't noise-promote)."""
    store = _fresh_store(tmpdir)
    _seed_shadow(store, 10, max_ticks=2)

    # Force dry_run to return an empty preview: no sources fetched any items.
    from donna.attention.dry_run import DryRunResult
    import donna.attention.promote as promote_mod

    def empty_dry_run(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(),
            rendered_markdown="",
        )

    original = promote_mod.dry_run
    promote_mod.dry_run = empty_dry_run  # type: ignore
    try:
        for _ in range(3):  # enough cycles to exhaust max_ticks=2
            run_shadow_cycle(store=store)
    finally:
        promote_mod.dry_run = original  # type: ignore

    attentions = store.list()
    archived = sum(
        1 for a in attentions if a.status is AttentionStatus.QUIETLY_ARCHIVED
    )
    pct = archived / len(attentions) if attentions else 0.0
    return EvalResult(
        name="promotion_decay",
        target="≥ 50% archived when signal absent",
        measured=f"{archived}/{len(attentions)} = {pct:.0%}",
        passed=pct >= 0.5,
    )


def eval_duplicate_suppression(tmpdir: Path) -> EvalResult:
    """#6: re-running propose_and_shadow with no signal change adds nothing new."""

    class _FakeFetcher:
        def __init__(self, events):
            self._events = events

        def fetch(self, source, user_id):
            return list(self._events)

    events = [
        {"id": "1", "title": "Recurring daily"},
        {"id": "2", "title": "Recurring daily"},
    ]
    proposer = CalendarRecurrenceProposer(fetcher=_FakeFetcher(events))
    store = _fresh_store(tmpdir)

    # Skip the LLM: force author fallback.
    import donna.attention.author as author_mod

    original = author_mod._call_with_validation_retry

    async def fake_none(**kwargs):
        return None

    author_mod._call_with_validation_retry = fake_none  # type: ignore

    try:
        first = asyncio.run(
            propose_and_shadow(
                "eval-user", proposers=(proposer,), store=store
            )
        )
        second = asyncio.run(
            propose_and_shadow(
                "eval-user", proposers=(proposer,), store=store
            )
        )
    finally:
        author_mod._call_with_validation_retry = original  # type: ignore

    new_in_second = sum(1 for r in second if r.attention is not None)
    return EvalResult(
        name="duplicate_suppression",
        target="0 new shadows on second run",
        measured=(
            f"run1 authored={sum(1 for r in first if r.attention)}, "
            f"run2 authored={new_in_second}"
        ),
        passed=new_in_second == 0,
    )


def eval_offer_idempotency(tmpdir: Path) -> EvalResult:
    """#7: accept/reject are no-ops on wrong-status attentions."""
    store = _fresh_store(tmpdir)
    poke = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec

    def make_with_status(status: AttentionStatus) -> Attention:
        a = Attention(
            user_id=uuid4(),
            spec=poke,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=status,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState() if status is AttentionStatus.SHADOW else None,
        )
        store.save(a)
        return a

    wrong_statuses = [
        AttentionStatus.LIVE,
        AttentionStatus.SHADOW,
        AttentionStatus.REJECTED,
        AttentionStatus.RESOLVED,
    ]
    failures: list[str] = []
    for status in wrong_statuses:
        a = make_with_status(status)
        if accept_offer(str(a.id), store=store) is not None:
            failures.append(f"accept on {status.value} mutated")
        if reject_offer(str(a.id), store=store) is not None:
            failures.append(f"reject on {status.value} mutated")

    # And confirm the happy path still works.
    offered = make_with_status(AttentionStatus.OFFERED)
    if accept_offer(str(offered.id), store=store) is None:
        failures.append("accept on OFFERED returned None")

    return EvalResult(
        name="offer_idempotency",
        target="accept/reject no-op on non-OFFERED statuses",
        measured=f"{len(failures)} failures" if failures else "all guards held",
        passed=not failures,
        notes="; ".join(failures),
    )


# -- Driver ------------------------------------------------------------------


EVALS: tuple[tuple[str, Callable[[Path], EvalResult]], ...] = (
    ("#3 shadow_tick_latency", eval_shadow_tick_latency),
    ("#5 promotion_decay", eval_promotion_decay),
    ("#6 duplicate_suppression", eval_duplicate_suppression),
    ("#7 offer_idempotency", eval_offer_idempotency),
)


def run_all(tmpdir: Path | None = None) -> list[EvalResult]:
    import tempfile

    if tmpdir is None:
        tmpdir = Path(tempfile.mkdtemp(prefix="donna_eval_"))
    results: list[EvalResult] = []
    for label, fn in EVALS:
        try:
            r = fn(tmpdir)
        except Exception as e:
            r = EvalResult(
                name=label, target="did not raise", measured="exception",
                passed=False, notes=repr(e),
            )
        results.append(r)
    return results


def format_markdown(results: list[EvalResult]) -> str:
    lines = ["| eval | target | measured | pass |", "|---|---|---|---|"]
    for r in results:
        mark = "OK" if r.passed else "FAIL"
        lines.append(
            f"| {r.name} | {r.target} | {r.measured} | {mark} |"
        )
    passed = sum(1 for r in results if r.passed)
    lines.append(f"\n**{passed}/{len(results)} passed.**")
    return "\n".join(lines)


def format_csv(results: list[EvalResult]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "target", "measured", "passed", "notes"])
    for r in results:
        w.writerow([r.name, r.target, r.measured, r.passed, r.notes])
    return buf.getvalue()


def main() -> int:
    results = run_all()
    print(format_markdown(results))
    report_path = Path(__file__).parent / "PROACTIVE_EVAL_REPORT.md"
    report_path.write_text(
        "# Proactive loop eval report\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n\n"
        + format_markdown(results)
        + "\n"
    )
    csv_path = Path(__file__).parent / "proactive_eval.csv"
    csv_path.write_text(format_csv(results))
    print(f"\nreport: {report_path}")
    print(f"csv:    {csv_path}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
