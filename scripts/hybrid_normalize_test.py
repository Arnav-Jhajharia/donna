"""Condition C: hybrid normalize.

Rule: use heuristic normalize by default. Call LLM normalize only when the
retrieval stage is not confident about the intent (top-1 cosine < threshold)
or the intent is very short (<4 tokens). The former covers the case where
the gold library doesn't have a good match so the author gets less help.
The latter covers terse intents that give Haiku too little to work with.

Compare C against A (always-LLM-normalize) and B (always-blank-normalize)
from the previous variance run.
"""
from __future__ import annotations

import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from donna.attention.author import AuthorResult, author_spec  # noqa: E402
from donna.attention.normalize import (  # noqa: E402
    NormalizedIntent,
    UserContext,
    _heuristic_normalize,
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
SCORE_THRESHOLD = 0.15
MIN_TOKENS = 4


def _fingerprint(spec) -> dict:
    return {
        "card": spec.card.value,
        "cadence": spec.cadence.type.value,
        "subject_type": spec.subject.type.value,
        "sources": sorted(s.type.value for s in spec.sources),
        "domain_tags": sorted(t.value for t in spec.domain_tags),
    }


def _agreement(fps: list[dict]) -> float:
    if len(fps) < 2:
        return 1.0
    pairs = matches = 0
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            pairs += 1
            if fps[i] == fps[j]:
                matches += 1
    return matches / pairs


def _word_count(intent: str) -> int:
    return len(re.findall(r"\w+", intent))


async def _smart_normalize(
    intent: str,
    user_ctx: UserContext,
    retrieved,
) -> tuple[NormalizedIntent, str, float]:
    """Return (normalized_intent, which_path, normalize_ms)."""
    top_score = retrieved[0].score if retrieved else 0.0
    short = _word_count(intent) < MIN_TOKENS

    t0 = time.perf_counter()
    if short or top_score < SCORE_THRESHOLD:
        normalized = await normalize_intent(intent, user_ctx)
        which = f"llm(score={top_score:.3f},short={short})"
    else:
        normalized = _heuristic_normalize(intent)
        which = f"heuristic(score={top_score:.3f})"
    ms = (time.perf_counter() - t0) * 1000
    return normalized, which, ms


async def _run_once(intent: str, user_ctx: UserContext) -> dict:
    t_total = time.perf_counter()

    t0 = time.perf_counter()
    retrieved = retrieve_top_k(intent, k=3)
    retrieve_ms = (time.perf_counter() - t0) * 1000

    normalized, which, normalize_ms = await _smart_normalize(intent, user_ctx, retrieved)

    t0 = time.perf_counter()
    authored: AuthorResult = await author_spec(normalized, user_ctx, retrieved=retrieved)
    author_ms = (time.perf_counter() - t0) * 1000

    total_ms = (time.perf_counter() - t_total) * 1000
    return {
        "fingerprint": _fingerprint(authored.spec),
        "via": authored.via,
        "cost_usd": authored.usage.cost_usd if authored.usage else 0.0,
        "normalize_path": which,
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
        runs = []
        for r in range(N_RUNS):
            res = await _run_once(intent, user_ctx)
            runs.append(res)
            fp = res["fingerprint"]
            print(f"   C{r+1}: {fp['card']:<12} {fp['cadence']:<10} "
                  f"src={fp['sources']} ${res['cost_usd']:.4f} {res['total_ms']:.0f}ms "
                  f"path={res['normalize_path']}")
        within = _agreement([r["fingerprint"] for r in runs])
        card_stable = len({r["fingerprint"]["card"] for r in runs}) == 1
        cadence_stable = len({r["fingerprint"]["cadence"] for r in runs}) == 1
        report.append(
            {
                "intent": intent,
                "runs": runs,
                "within_agreement": round(within, 3),
                "card_stable": card_stable,
                "cadence_stable": cadence_stable,
            }
        )
        print(f"   agreement C-C={within:.2f}  card_stable={card_stable}  cadence_stable={cadence_stable}")

    # --- Load A/B from prior run -----------------------------------------
    prev = ROOT / "scripts" / "_out" / "variance_and_ablate.json"
    prior = json.loads(prev.read_text()) if prev.exists() else []

    out = ROOT / "scripts" / "_out" / "hybrid_normalize.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    c_costs = [r["cost_usd"] for row in report for r in row["runs"]]
    c_ms = [r["total_ms"] for row in report for r in row["runs"]]
    c_norm_ms = [r["normalize_ms"] for row in report for r in row["runs"]]
    paths = [r["normalize_path"].split("(")[0] for row in report for r in row["runs"]]
    n_heuristic = paths.count("heuristic")
    n_llm = paths.count("llm")

    print("\n" + "=" * 70)
    print("AGGREGATE C (hybrid normalize)")
    print("=" * 70)
    print(f"runs: {N_RUNS} per intent x {len(INTENTS)} intents = {len(c_costs)} runs")
    print(f"path taken: heuristic={n_heuristic}/{len(paths)}  llm={n_llm}/{len(paths)}")
    print(f"cost mean: ${statistics.mean(c_costs):.5f}  median: ${statistics.median(c_costs):.5f}")
    print(f"latency mean: {statistics.mean(c_ms):.0f}ms  median: {statistics.median(c_ms):.0f}ms")
    print(f"normalize-stage mean: {statistics.mean(c_norm_ms):.0f}ms")
    card_stable = sum(1 for r in report if r["card_stable"])
    cadence_stable = sum(1 for r in report if r["cadence_stable"])
    print(f"card stable (within C): {card_stable}/{len(report)}")
    print(f"cadence stable (within C): {cadence_stable}/{len(report)}")
    avg_within_c = statistics.mean(r["within_agreement"] for r in report)
    print(f"avg within-agreement C-C: {avg_within_c:.3f}")

    if prior:
        a_costs = [r["cost_usd"] for row in prior for r in row["A_runs"]]
        b_costs = [r["cost_usd"] for row in prior for r in row["B_runs"]]
        a_ms = [r["total_ms"] for row in prior for r in row["A_runs"]]
        b_ms = [r["total_ms"] for row in prior for r in row["B_runs"]]
        a_within = statistics.mean(r["A_within_agreement"] for r in prior)
        b_within = statistics.mean(r["B_within_agreement"] for r in prior)

        print()
        print("COMPARISON TABLE")
        print("-" * 70)
        print(f"{'':<30}{'A (LLM)':>13}{'B (blank)':>13}{'C (hybrid)':>13}")
        print(f"{'mean cost / call':<30}{'$' + f'{statistics.mean(a_costs):.5f}':>13}"
              f"{'$' + f'{statistics.mean(b_costs):.5f}':>13}"
              f"{'$' + f'{statistics.mean(c_costs):.5f}':>13}")
        print(f"{'mean latency / call (ms)':<30}{statistics.mean(a_ms):>13.0f}"
              f"{statistics.mean(b_ms):>13.0f}{statistics.mean(c_ms):>13.0f}")
        print(f"{'within-group agreement':<30}{a_within:>13.3f}{b_within:>13.3f}{avg_within_c:>13.3f}")

        # cross-condition agreement: pool all fingerprints per intent
        cross = []
        for idx, row in enumerate(report):
            c_fps = [r["fingerprint"] for r in row["runs"]]
            a_fps = [r["fingerprint"] for r in prior[idx]["A_runs"]]
            ac = _agreement(a_fps + c_fps)
            cross.append(ac)
        print(f"{'pooled A+C agreement':<30}{'':>13}{'':>13}{statistics.mean(cross):>13.3f}")

        a_cost_total = statistics.mean(a_costs)
        c_cost_total = statistics.mean(c_costs)
        cost_savings_pct = (a_cost_total - c_cost_total) / a_cost_total * 100
        latency_savings_pct = (statistics.mean(a_ms) - statistics.mean(c_ms)) / statistics.mean(a_ms) * 100
        print()
        print(f"C vs A: cost {cost_savings_pct:+.1f}%  latency {latency_savings_pct:+.1f}%")

    print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
