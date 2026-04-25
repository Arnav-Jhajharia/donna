"""Ablation: does normalize actually help the author?

For each of the 10 intents, run the author step twice:
  A) with real Haiku-produced NormalizedSignals (full pipeline)
  B) with blank signals (normalize bypassed; author sees raw text only)

Compare the authored specs on: card, cadence type, subject name/type,
source list, domain_tags, surface default.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from donna.attention.author import author_spec  # noqa: E402
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


def _fingerprint(spec) -> dict:
    return {
        "card": spec.card.value,
        "cadence": spec.cadence.type.value,
        "cadence_params": spec.cadence.params,
        "subject_name": spec.subject.name,
        "subject_type": spec.subject.type.value,
        "sources": [s.type.value for s in spec.sources],
        "domain_tags": [t.value for t in spec.domain_tags],
        "surface_default": spec.surface_policy.default.value,
        "urgent_if": spec.surface_policy.urgent_if,
    }


def _blank_normalized(intent: str) -> NormalizedIntent:
    return NormalizedIntent(
        raw_text=intent,
        normalized_text=intent,
        signals=NormalizedSignals(),  # all defaults
    )


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
        print(f"[{i:2d}/{len(INTENTS)}] {intent}", flush=True)
        retrieved = retrieve_top_k(intent, k=3)

        # A: real normalize
        norm_real = await normalize_intent(intent, user_ctx)
        a_res = await author_spec(norm_real, user_ctx, retrieved=retrieved)

        # B: blank normalize
        norm_blank = _blank_normalized(intent)
        b_res = await author_spec(norm_blank, user_ctx, retrieved=retrieved)

        a_fp = _fingerprint(a_res.spec)
        b_fp = _fingerprint(b_res.spec)
        diffs = {k: (a_fp[k], b_fp[k]) for k in a_fp if a_fp[k] != b_fp[k]}

        report.append(
            {
                "intent": intent,
                "real_normalize_signals": norm_real.signals.model_dump(),
                "A_with_normalize": a_fp,
                "B_blank_normalize": b_fp,
                "differences": diffs,
                "A_via": a_res.via,
                "B_via": b_res.via,
                "A_cost": round(a_res.usage.cost_usd, 6) if a_res.usage else None,
                "B_cost": round(b_res.usage.cost_usd, 6) if b_res.usage else None,
            }
        )

        print(f"     A card={a_fp['card']:<12} cadence={a_fp['cadence']:<10} sources={a_fp['sources']}")
        print(f"     B card={b_fp['card']:<12} cadence={b_fp['cadence']:<10} sources={b_fp['sources']}")
        if diffs:
            print(f"     DIFFS: {list(diffs.keys())}")
        else:
            print(f"     (identical fingerprints)")

    out = ROOT / "scripts" / "_out" / "ablate_normalize.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")

    same = sum(1 for r in report if not r["differences"])
    print(f"\n{same}/{len(report)} intents had IDENTICAL fingerprint with or without normalize")


if __name__ == "__main__":
    asyncio.run(main())
