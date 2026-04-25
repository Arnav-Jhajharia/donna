"""A/B variance test for the normalize stage.

For each intent, run:
  A) real pipeline (normalize -> retrieve -> author -> dry_run) x3
  B) blank-normalize pipeline (skip normalize LLM call) x3

Measure:
  - within-group fingerprint agreement (does the same config give the same spec?)
  - between-group fingerprint agreement (does normalize change the spec?)
  - cost per run, latency per run
  - aggregate cost/latency delta from removing normalize

A's contribution is credible only if within-group agreement is HIGHER than
between-group agreement. If A-A variance ~ A-B variance, normalize is noise.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from donna.attention.author import AuthorResult, _looks_like_bare_reminder, author_spec  # noqa: E402
from donna.attention.dry_run import dry_run  # noqa: E402
from donna.attention.harness import PipelineResult, StageTiming  # noqa: E402
from donna.attention.normalize import (  # noqa: E402
    NormalizedIntent,
    NormalizedSignals,
    UserContext,
    normalize_intent,
)
from donna.attention.retrieve import retrieve_top_k  # noqa: E402

INTENTS: list[str] = [
    "keep an eye on ICA for anything about EP renewal rules",
    "watch RBI, ping me when they move rates",
    "track my grab spend this month, flag if i cross 400 sgd",
    "every friday evening summarise how nifty and sgx moved this week",
    "monday 8am digest of indian startup funding rounds over 5m",
    "30 min before any call with a mumbai client pull their last 3 emails",
    "brief me before my 1:1 with the dbs rm next wed",
    "chase the iras gst refund, nudge me if nothing in 10 days",
    "close the loop on the term sheet we sent accel last tuesday",
    "remind me to pay mcst on the 5th every month",
]

N_RUNS = 3


def _fingerprint(spec) -> dict:
    return {
        "card": spec.card.value,
        "cadence": spec.cadence.type.value,
        "subject_type": spec.subject.type.value,
        "sources": sorted(s.type.value for s in spec.sources),
        "domain_tags": sorted(t.value for t in spec.domain_tags),
    }


def _fp_eq(a: dict, b: dict) -> bool:
    return a == b


def _agreement(fps: list[dict]) -> float:
    if len(fps) < 2:
        return 1.0
    pairs = 0
    matches = 0
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            pairs += 1
            if _fp_eq(fps[i], fps[j]):
                matches += 1
    return matches / pairs


def _blank_normalized(intent: str) -> NormalizedIntent:
    return NormalizedIntent(
        raw_text=intent,
        normalized_text=intent,
        signals=NormalizedSignals(),
    )


async def _run_once(
    intent: str,
    user_ctx: UserContext,
    *,
    skip_normalize: bool,
) -> dict:
    t_total = time.perf_counter()
    t0 = time.perf_counter()
    if skip_normalize or _looks_like_bare_reminder(intent):
        normalized = _blank_normalized(intent)
    else:
        normalized = await normalize_intent(intent, user_ctx)
    normalize_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    retrieved = retrieve_top_k(intent, k=3)
    retrieve_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    authored: AuthorResult = await author_spec(normalized, user_ctx, retrieved=retrieved)
    author_ms = (time.perf_counter() - t0) * 1000

    total_ms = (time.perf_counter() - t_total) * 1000
    return {
        "fingerprint": _fingerprint(authored.spec),
        "via": authored.via,
        "cost_usd": authored.usage.cost_usd if authored.usage else 0.0,
        "normalize_ms": round(normalize_ms, 1),
        "retrieve_ms": round(retrieve_ms, 1),
        "author_ms": round(author_ms, 1),
        "total_ms": round(total_ms, 1),
    }


async def main() -> None:
    user_ctx = UserContext(
        user_id=str(uuid4()),
        living_profile=(
            "Arnav, 28, Mumbai-based founder spending time in Singapore. "
            "Works across India and SG. Raising a seed round. Lowercase texter."
        ),
    )

    report: list[dict] = []
    for i, intent in enumerate(INTENTS, 1):
        print(f"\n[{i:2d}/{len(INTENTS)}] {intent}", flush=True)

        a_runs = []
        for r in range(N_RUNS):
            res = await _run_once(intent, user_ctx, skip_normalize=False)
            a_runs.append(res)
            print(f"   A{r+1}: {res['fingerprint']['card']:<12} {res['fingerprint']['cadence']:<10} "
                  f"src={res['fingerprint']['sources']} "
                  f"${res['cost_usd']:.4f} {res['total_ms']:.0f}ms")

        b_runs = []
        for r in range(N_RUNS):
            res = await _run_once(intent, user_ctx, skip_normalize=True)
            b_runs.append(res)
            print(f"   B{r+1}: {res['fingerprint']['card']:<12} {res['fingerprint']['cadence']:<10} "
                  f"src={res['fingerprint']['sources']} "
                  f"${res['cost_usd']:.4f} {res['total_ms']:.0f}ms")

        a_fps = [r["fingerprint"] for r in a_runs]
        b_fps = [r["fingerprint"] for r in b_runs]
        a_within = _agreement(a_fps)
        b_within = _agreement(b_fps)
        between = _agreement(a_fps + b_fps)

        card_stable = len({fp["card"] for fp in a_fps + b_fps}) == 1
        cadence_stable = len({fp["cadence"] for fp in a_fps + b_fps}) == 1

        report.append(
            {
                "intent": intent,
                "A_runs": a_runs,
                "B_runs": b_runs,
                "A_within_agreement": round(a_within, 3),
                "B_within_agreement": round(b_within, 3),
                "between_agreement": round(between, 3),
                "card_stable_across_all": card_stable,
                "cadence_stable_across_all": cadence_stable,
            }
        )
        print(f"   agreement  A-A={a_within:.2f}  B-B={b_within:.2f}  A-B(all)={between:.2f}  "
              f"card_stable={card_stable}  cadence_stable={cadence_stable}")

    out = ROOT / "scripts" / "_out" / "variance_and_ablate.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ---- Aggregates -------------------------------------------------------
    a_costs = [r["cost_usd"] for row in report for r in row["A_runs"]]
    b_costs = [r["cost_usd"] for row in report for r in row["B_runs"]]
    a_ms = [r["total_ms"] for row in report for r in row["A_runs"]]
    b_ms = [r["total_ms"] for row in report for r in row["B_runs"]]
    a_norm_ms = [r["normalize_ms"] for row in report for r in row["A_runs"]]
    b_norm_ms = [r["normalize_ms"] for row in report for r in row["B_runs"]]

    a_within_avg = statistics.mean(r["A_within_agreement"] for r in report)
    b_within_avg = statistics.mean(r["B_within_agreement"] for r in report)
    between_avg = statistics.mean(r["between_agreement"] for r in report)
    card_stable_n = sum(1 for r in report if r["card_stable_across_all"])
    cadence_stable_n = sum(1 for r in report if r["cadence_stable_across_all"])

    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)
    print(f"runs: {N_RUNS}x A and {N_RUNS}x B for {len(INTENTS)} intents "
          f"= {len(a_costs)} A-calls, {len(b_costs)} B-calls")
    print()
    print("AGREEMENT (higher = more consistent fingerprint):")
    print(f"  A-A (within real-normalize):   {a_within_avg:.3f}")
    print(f"  B-B (within blank-normalize):  {b_within_avg:.3f}")
    print(f"  A-B (pooled across both):      {between_avg:.3f}")
    print(f"  → if A-A ≈ A-B, normalize is noise-indistinguishable")
    print()
    print("STRUCTURAL STABILITY:")
    print(f"  card stable across all 6 runs:    {card_stable_n}/{len(report)}")
    print(f"  cadence stable across all 6 runs: {cadence_stable_n}/{len(report)}")
    print()
    print("COST PER CALL (USD):")
    print(f"  A mean: ${statistics.mean(a_costs):.5f}   median: ${statistics.median(a_costs):.5f}")
    print(f"  B mean: ${statistics.mean(b_costs):.5f}   median: ${statistics.median(b_costs):.5f}")
    print(f"  Δ (A-B): ${statistics.mean(a_costs) - statistics.mean(b_costs):+.5f} "
          f"({(statistics.mean(a_costs) - statistics.mean(b_costs)) / max(statistics.mean(b_costs), 1e-9) * 100:+.1f}%)")
    print()
    print("LATENCY PER CALL (ms):")
    print(f"  A mean: {statistics.mean(a_ms):.0f}   median: {statistics.median(a_ms):.0f}")
    print(f"  B mean: {statistics.mean(b_ms):.0f}   median: {statistics.median(b_ms):.0f}")
    print(f"  Δ (A-B): {statistics.mean(a_ms) - statistics.mean(b_ms):+.0f}ms "
          f"({(statistics.mean(a_ms) - statistics.mean(b_ms)) / max(statistics.mean(b_ms), 1e-9) * 100:+.1f}%)")
    print()
    print("NORMALIZE STAGE COST (A only, ms):")
    print(f"  A normalize mean: {statistics.mean(a_norm_ms):.0f}ms   median: {statistics.median(a_norm_ms):.0f}ms")
    print(f"  B normalize mean: {statistics.mean(b_norm_ms):.0f}ms   (blank path, ~0)")
    print()
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
