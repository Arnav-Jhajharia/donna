"""Stress-test donna.attention with 10 SG/IN professional intents.

Runs each intent through the full pipeline (normalize -> retrieve -> author
-> dry_run), captures the authored AttentionSpec, stage timings, token usage,
and the dry-run preview. Writes a JSON report to scripts/_out/attention_run.json
and prints a compact table to stdout.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from donna.attention.harness import run_attention_pipeline  # noqa: E402
from donna.attention.normalize import UserContext  # noqa: E402

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


def _spec_to_dict(spec) -> dict:
    return spec.model_dump(mode="json")


def _summary(result) -> dict:
    authored = result.authored
    spec = authored.spec
    usage = authored.usage
    timings = {t.stage: round(t.ms, 1) for t in result.timings}
    return {
        "raw_intent": result.raw_intent,
        "timings_ms": timings,
        "total_ms": round(result.total_ms, 1),
        "via": authored.via,
        "confidence": authored.confidence,
        "retrieved_ids": list(authored.retrieved_ids),
        "normalized_signals": result.normalized.signals.model_dump(),
        "normalized_text": result.normalized.normalized_text,
        "spec": _spec_to_dict(spec),
        "usage": asdict(usage) if usage else None,
        "cost_usd": round(usage.cost_usd, 6) if usage else None,
        "preview_markdown": result.preview.rendered_markdown,
        "preview_warnings": list(result.preview.warnings),
    }


async def main() -> None:
    user_ctx = UserContext(
        user_id=str(uuid4()),
        living_profile=(
            "Arnav, 28, Mumbai-based founder spending time in Singapore. "
            "Works across India and SG. Raising a seed round. Lowercase texter."
        ),
        active_state="",
    )

    results: list[dict] = []
    for i, intent in enumerate(INTENTS, 1):
        print(f"[{i:2d}/{len(INTENTS)}] {intent}", flush=True)
        try:
            result = await run_attention_pipeline(intent, user_ctx, k=3)
            summary = _summary(result)
        except Exception as e:
            summary = {"raw_intent": intent, "error": repr(e)}
            print(f"     ERROR: {e!r}")
        results.append(summary)

        if "error" not in summary:
            spec = summary["spec"]
            print(
                f"     card={spec['card']:<12} cadence={spec['cadence']['type']:<10} "
                f"sources={[s['type'] for s in spec['sources']]} "
                f"via={summary['via']:<4} cost=${summary['cost_usd']} "
                f"total={summary['total_ms']}ms"
            )

    out_dir = ROOT / "scripts" / "_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "attention_run.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")

    total_cost = sum(r.get("cost_usd") or 0 for r in results)
    total_ms = sum(r.get("total_ms") or 0 for r in results)
    ok = sum(1 for r in results if "error" not in r)
    print(
        f"summary: {ok}/{len(INTENTS)} ok · total_cost=${total_cost:.4f} · "
        f"total_ms={total_ms:.0f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
