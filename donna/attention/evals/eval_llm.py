"""LLM-gated evals for the proactive loop.

Run: `python -m donna.attention.evals.eval_llm`

Covers parameters from the testing spec that require labeled data and/or
live model calls:
  #1 proposer precision    (accept-rate of emitted candidates)
  #2 proposer recall       (fraction of should-propose signals caught)
  #4 hit calibration       (hit detector agrees with human label)
  #8 author retry rate     (fraction of author calls that hit retry)
  #9 cost per cycle        ($/propose+shadow cycle, mean over candidates)
  #10 conversion time       (SHADOW → OFFERED wall-clock, min/median)

Gold file: ``gold_candidates.jsonl`` next to this module. Each line is a
labeled record; the ``kind`` field selects which eval consumes it:

  - ``proposer``        : precision ground truth (accept | reject)
  - ``proposer_recall`` : recall ground truth (should_propose true/false)
  - ``hit``             : hit-calibration ground truth (is_real_hit)

Outputs: ``LLM_EVAL_REPORT.md`` + ``llm_eval.csv`` next to this module.

Costs real money when fully wired. Guarded by ``DONNA_RUN_LLM_EVAL=1`` so
a CI run or an accidental invocation can't drain the budget.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from donna.attention.dry_run import DryRunResult, SourcePreview
from donna.attention.harness import run_attention_pipeline
from donna.attention.normalize import UserContext
from donna.attention.promote import _is_hit, run_shadow_cycle
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
from donna.attention.vocabulary import SourceType


GOLD_PATH = Path(__file__).parent / "gold_candidates.jsonl"


# -- Types -------------------------------------------------------------------


@dataclass
class LLMEvalResult:
    name: str
    target: str
    measured: str
    passed: bool
    samples: int = 0
    notes: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoldRecord:
    id: str
    kind: str
    raw: dict[str, Any]


def load_gold() -> list[GoldRecord]:
    if not GOLD_PATH.exists():
        return []
    out: list[GoldRecord] = []
    for line in GOLD_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rec = json.loads(line)
        out.append(GoldRecord(id=rec["id"], kind=rec["kind"], raw=rec))
    return out


def _by_kind(records: list[GoldRecord], kind: str) -> list[GoldRecord]:
    return [r for r in records if r.kind == kind]


# -- #1 proposer precision ---------------------------------------------------


def eval_proposer_precision(records: list[GoldRecord]) -> LLMEvalResult:
    """#1: of candidates the proposer actually emits, what fraction are
    human-labeled ``accept``?

    Builds a synthetic calendar fetcher from gold signals (one fake event
    per recurrence so the proposer's repeat detector fires), runs the
    calendar proposer, then scores emitted raw_intents against labels.
    Rows the proposer correctly suppresses don't count against precision.
    """
    rows = [
        r for r in _by_kind(records, "proposer")
        if r.raw.get("proposer") == "calendar_recurrence"
    ]
    if not rows:
        return LLMEvalResult(
            name="proposer_precision",
            target="≥ 0.80",
            measured="no gold rows",
            passed=False,
            notes="populate gold_candidates.jsonl with kind=proposer rows",
        )

    events: list[dict[str, Any]] = []
    for row in rows:
        sig = row.raw.get("signal", {})
        title = sig.get("title", "")
        for i in range(int(sig.get("recurrences", 0))):
            events.append({"id": f"{row.id}-{i}", "title": title})

    class _FakeFetcher:
        def fetch(self, source, user_id):
            return list(events)

    proposer = CalendarRecurrenceProposer(fetcher=_FakeFetcher())
    emitted = {c.raw_intent for c in proposer.propose("eval-user")}

    # Map row → emitted? Match by substring of the title in raw_intent.
    tp = 0  # emitted AND accept
    fp = 0  # emitted AND reject
    suppressed_rejects = 0
    missed_accepts = 0
    for row in rows:
        title = row.raw.get("signal", {}).get("title", "")
        was_emitted = any(title in e for e in emitted)
        label = row.raw.get("label")
        if was_emitted and label == "accept":
            tp += 1
        elif was_emitted and label == "reject":
            fp += 1
        elif not was_emitted and label == "reject":
            suppressed_rejects += 1
        elif not was_emitted and label == "accept":
            missed_accepts += 1

    total_emitted = tp + fp
    precision = tp / total_emitted if total_emitted else 0.0
    return LLMEvalResult(
        name="proposer_precision",
        target="≥ 0.80",
        measured=(
            f"{tp}/{total_emitted} = {precision:.0%} "
            f"(suppressed_rejects={suppressed_rejects}, missed_accepts={missed_accepts})"
        ),
        passed=precision >= 0.80 and total_emitted > 0,
        samples=len(rows),
        details={
            "tp": tp, "fp": fp,
            "suppressed_rejects": suppressed_rejects,
            "missed_accepts": missed_accepts,
        },
    )


# -- #2 proposer recall ------------------------------------------------------


def eval_proposer_recall(records: list[GoldRecord]) -> LLMEvalResult:
    """#2: of signals gold-labeled should_propose=true, how many did the
    proposer actually emit?

    Placeholder today — calibration of this requires running each proposer
    against the gold signal and checking if the expected raw_intent appears
    in the output. Real implementation needs a signal-injection shim per
    proposer (calendar fetcher stub, chat fetcher stub, etc). Tracked.
    """
    rows = [r for r in _by_kind(records, "proposer_recall") if r.raw.get("should_propose")]
    if not rows:
        return LLMEvalResult(
            name="proposer_recall",
            target="≥ 0.70",
            measured="no gold rows",
            passed=False,
            notes="populate gold with kind=proposer_recall, should_propose=true",
        )
    return LLMEvalResult(
        name="proposer_recall",
        target="≥ 0.70",
        measured="pending — needs signal-injection shims",
        passed=False,
        samples=len(rows),
        notes="implement per-proposer fetcher stubs, then match emitted raw_intent against gold",
    )


# -- #4 hit calibration ------------------------------------------------------


def eval_hit_calibration(records: list[GoldRecord]) -> LLMEvalResult:
    """#4: does `_is_hit` agree with the human label on gold tick examples?"""
    rows = _by_kind(records, "hit")
    if not rows:
        return LLMEvalResult(
            name="hit_calibration",
            target="agreement ≥ 0.85",
            measured="no gold rows",
            passed=False,
            notes="populate gold with kind=hit",
        )

    from donna.attention.vocabulary import CardType

    def _synth_preview(tick_sources: dict[str, int]) -> DryRunResult:
        previews = tuple(
            SourcePreview(
                source_type=SourceType(src),
                item_count=cnt,
                sample=[],
            )
            for src, cnt in tick_sources.items()
        )
        return DryRunResult(
            spec_title="synthetic",
            card=CardType.EVENT_STREAM,
            source_previews=previews,
            rendered_markdown="",
        )

    agree = 0
    disagreements: list[str] = []
    for r in rows:
        expected = bool(r.raw.get("is_real_hit"))
        try:
            preview = _synth_preview(r.raw.get("tick_sources", {}))
        except ValueError as e:
            disagreements.append(f"{r.id}: bad source ({e})")
            continue
        got = _is_hit(preview)
        if got == expected:
            agree += 1
        else:
            disagreements.append(
                f"{r.id}: expected {expected}, got {got}"
            )
    pct = agree / len(rows)
    return LLMEvalResult(
        name="hit_calibration",
        target="agreement ≥ 0.85",
        measured=f"{agree}/{len(rows)} = {pct:.0%}",
        passed=pct >= 0.85,
        samples=len(rows),
        notes="; ".join(disagreements[:3]),
        details={"disagreements": disagreements},
    )


# -- #8 author retry rate ----------------------------------------------------


async def eval_author_retry_rate(records: list[GoldRecord]) -> LLMEvalResult:
    """#8: run `propose_and_shadow` over a fixed signal set; count how many
    author calls needed the validation retry.

    Requires live LLM. Currently instruments via `authored.via` on each
    PipelineResult — any value prefixed "retry" counts as a retry.
    """
    if os.environ.get("DONNA_RUN_LLM_EVAL") != "1":
        return LLMEvalResult(
            name="author_retry_rate",
            target="≤ 0.15",
            measured="skipped (DONNA_RUN_LLM_EVAL != 1)",
            passed=False,
            notes="set DONNA_RUN_LLM_EVAL=1 to execute",
        )

    ctx = UserContext(user_id="eval-user")
    rows = _by_kind(records, "proposer")
    if not rows:
        return LLMEvalResult(
            name="author_retry_rate",
            target="≤ 0.15",
            measured="no gold rows",
            passed=False,
        )
    retries = 0
    errors = 0
    for r in rows:
        try:
            result = await run_attention_pipeline(r.raw["raw_intent"], ctx)
            if result.authored.via.startswith("retry"):
                retries += 1
        except Exception:
            errors += 1
    rate = retries / len(rows)
    return LLMEvalResult(
        name="author_retry_rate",
        target="≤ 0.15",
        measured=f"{retries}/{len(rows)} = {rate:.0%}",
        passed=rate <= 0.15 and errors == 0,
        samples=len(rows),
        details={"retries": retries, "errors": errors},
    )


# -- #9 cost per cycle -------------------------------------------------------


async def eval_cost_per_cycle(records: list[GoldRecord]) -> LLMEvalResult:
    """#9: mean USD per propose→shadow authoring cycle.

    Reads ``AuthorResult.usage.cost_usd`` from each pipeline call.
    """
    if os.environ.get("DONNA_RUN_LLM_EVAL") != "1":
        return LLMEvalResult(
            name="cost_per_cycle",
            target="mean ≤ $0.01",
            measured="skipped (DONNA_RUN_LLM_EVAL != 1)",
            passed=False,
            notes="set DONNA_RUN_LLM_EVAL=1 to execute",
        )

    rows = _by_kind(records, "proposer")
    if not rows:
        return LLMEvalResult(
            name="cost_per_cycle",
            target="mean ≤ $0.01",
            measured="no gold rows",
            passed=False,
        )

    ctx = UserContext(user_id="eval-user")
    costs: list[float] = []
    missing = 0
    for r in rows:
        try:
            result = await run_attention_pipeline(r.raw["raw_intent"], ctx)
        except Exception:
            continue
        usage = result.authored.usage
        if usage is None:
            missing += 1
            continue
        costs.append(usage.cost_usd)
    if not costs:
        return LLMEvalResult(
            name="cost_per_cycle",
            target="mean ≤ $0.01",
            measured=f"no usage captured (missing={missing})",
            passed=False,
            notes="every call went through fallback / shortcircuit; no LLM tokens billed",
        )
    mean = sum(costs) / len(costs)
    max_cost = max(costs)
    return LLMEvalResult(
        name="cost_per_cycle",
        target="mean ≤ $0.01",
        measured=f"mean=${mean:.5f} max=${max_cost:.5f} n={len(costs)}",
        passed=mean <= 0.01,
        samples=len(costs),
        details={"costs": costs, "missing_usage": missing},
    )


# -- #10 conversion time -----------------------------------------------------


def eval_conversion_time(records: list[GoldRecord]) -> LLMEvalResult:
    """#10: wall-clock from SHADOW creation → OFFERED.

    Measured synthetically: seed N shadows, force all hits, run
    `run_shadow_cycle` until promotion, time the transition.
    """
    import tempfile
    from donna.attention.examples.gold_specs import GOLD_EXAMPLES
    import donna.attention.promote as promote_mod

    tmpdir = Path(tempfile.mkdtemp(prefix="donna_llm_eval_"))
    store = AttentionStore(path=tmpdir / f"store_{uuid4()}.json")
    poke = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec

    n = 5
    ids: list[str] = []
    for _ in range(n):
        a = Attention(
            user_id=uuid4(),
            spec=poke,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=AttentionStatus.SHADOW,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState(max_ticks=5),
        )
        store.save(a)
        ids.append(str(a.id))

    # Force hits on every tick.
    def always_hit(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(
                SourcePreview(
                    source_type=SourceType.WEB_EXA,
                    item_count=3,
                    sample=[],
                ),
            ),
            rendered_markdown="ok",
        )

    original = promote_mod.dry_run
    promote_mod.dry_run = always_hit  # type: ignore
    t0 = time.perf_counter()
    try:
        # Threshold is 2 hits, so two cycles are enough.
        for _ in range(3):
            run_shadow_cycle(store=store)
    finally:
        promote_mod.dry_run = original  # type: ignore
    elapsed_ms = (time.perf_counter() - t0) * 1000

    offered = sum(
        1 for a in store.list() if a.status is AttentionStatus.OFFERED
    )
    per_shadow_ms = elapsed_ms / n if n else 0.0
    return LLMEvalResult(
        name="conversion_time",
        target="median ≤ 500 ms per shadow (deterministic path)",
        measured=f"{per_shadow_ms:.1f} ms avg ({offered}/{n} offered)",
        passed=per_shadow_ms <= 500 and offered == n,
        samples=n,
        details={"elapsed_ms": elapsed_ms, "offered": offered},
    )


# -- Driver ------------------------------------------------------------------


SYNC_EVALS: tuple[tuple[str, Callable[[list[GoldRecord]], LLMEvalResult]], ...] = (
    ("#1 proposer_precision", eval_proposer_precision),
    ("#2 proposer_recall", eval_proposer_recall),
    ("#4 hit_calibration", eval_hit_calibration),
    ("#10 conversion_time", lambda _records: eval_conversion_time(_records)),
)

ASYNC_EVALS: tuple[tuple[str, Callable[[list[GoldRecord]], Any]], ...] = (
    ("#8 author_retry_rate", eval_author_retry_rate),
    ("#9 cost_per_cycle", eval_cost_per_cycle),
)


async def run_all() -> list[LLMEvalResult]:
    records = load_gold()
    results: list[LLMEvalResult] = []
    for label, fn in SYNC_EVALS:
        try:
            r = fn(records)
        except Exception as e:
            r = LLMEvalResult(
                name=label, target="did not raise", measured="exception",
                passed=False, notes=repr(e),
            )
        results.append(r)
    for label, fn in ASYNC_EVALS:
        try:
            r = await fn(records)
        except Exception as e:
            r = LLMEvalResult(
                name=label, target="did not raise", measured="exception",
                passed=False, notes=repr(e),
            )
        results.append(r)
    return results


def format_markdown(results: list[LLMEvalResult]) -> str:
    lines = [
        "| eval | target | measured | samples | pass |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        mark = "OK" if r.passed else "FAIL"
        lines.append(
            f"| {r.name} | {r.target} | {r.measured} | {r.samples} | {mark} |"
        )
    passed = sum(1 for r in results if r.passed)
    lines.append(f"\n**{passed}/{len(results)} passed.**")
    return "\n".join(lines)


def format_csv(results: list[LLMEvalResult]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "target", "measured", "samples", "passed", "notes"])
    for r in results:
        w.writerow([r.name, r.target, r.measured, r.samples, r.passed, r.notes])
    return buf.getvalue()


def main() -> int:
    results = asyncio.run(run_all())
    print(format_markdown(results))
    report_path = Path(__file__).parent / "LLM_EVAL_REPORT.md"
    report_path.write_text(
        "# Proactive loop — LLM-gated eval report\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat()}_\n\n"
        + format_markdown(results)
        + "\n"
    )
    csv_path = Path(__file__).parent / "llm_eval.csv"
    csv_path.write_text(format_csv(results))
    print(f"\nreport: {report_path}")
    print(f"csv:    {csv_path}")
    # Don't gate exit on the LLM-gated ones that are "pending" by design;
    # only fail if the deterministic pieces (#1, #4, #10) broke.
    must_pass = {"proposer_precision", "hit_calibration", "conversion_time"}
    return 0 if all(r.passed for r in results if r.name in must_pass) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
