"""Run the memory stress-test matrix.

Phase 3 of docs/memory-stress-test-plan.md. Loads the matrix, drives each
case through a turn runner, judges the reply, writes JSONL per run.

Modes:
    --dry-run              list the matrix, skip turns + judge
    --live                 run real turns via donna_runtime.runner.donna_turn
    (default)              dry-run equivalent with the stub runner

The --live path requires a seeded corpus (see scripts/seed_stress_corpus.py)
and real API credentials. When credentials are absent or the SDK can't
be imported, the CLI degrades to a stub runner and logs a warning — it
never pretends to have run real turns.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._seed_corpus.profile import SEED_USER_ID
from scripts._stress_matrix.cases import StressCase, all_cases
from scripts._stress_matrix.haiku_judge import build_judge_from_env
from scripts._stress_matrix.judge import JudgeClient
from scripts._stress_matrix.runner import TurnResult, TurnRunner, run_matrix
from scripts._stress_matrix.trace import StressTrace, summarize, write_jsonl

logger = logging.getLogger("run_memory_stress")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=SEED_USER_ID)
    parser.add_argument("--live", action="store_true", help="Fire real donna turns.")
    parser.add_argument("--dry-run", action="store_true", help="Enumerate cases only.")
    parser.add_argument(
        "--section",
        choices=[
            "single_hop",
            "multi_hop",
            "temporal",
            "derivation",
            "correction",
            "failure_injection",
            "voice_coherence",
        ],
    )
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--out",
        default=None,
        help="JSONL path. Default: scripts/_out/memory_stress_<run_id>.jsonl",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the Haiku judge even on --live runs (dev/debug only).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cases = _select_cases(args.section)
    if args.dry_run:
        for c in cases:
            print(f"{c.section:18} {c.id:32} {c.query}")
        print(f"total_cases={len(cases)}")
        return

    runner: TurnRunner = _select_runner(args.live)
    judge: JudgeClient | None = None if args.no_judge else _select_judge(args.live)
    rows = asyncio.run(
        run_matrix(
            cases,
            user_id=args.user_id,
            turn_runner=runner,
            judge_client=judge,
            concurrency=max(1, args.concurrency),
        )
    )

    out_path = Path(args.out) if args.out else _default_out_path()
    write_jsonl(out_path, rows)
    summary = summarize(rows)
    print(
        f"memory stress run out={out_path} "
        f"total={summary['total']} passed={summary['passed']} "
        f"failed={summary['failed']} error={summary['error']}"
    )
    for section, bucket in sorted(summary["by_section"].items()):
        print(f"  {section:20} passed={bucket['passed']} failed={bucket['failed']} error={bucket['error']}")


def _select_cases(section: str | None) -> list[StressCase]:
    cases = all_cases()
    if section:
        cases = [c for c in cases if c.section == section]
    return cases


def _default_out_path() -> Path:
    return ROOT / "scripts" / "_out" / f"memory_stress_{int(time.time())}.jsonl"


def _select_runner(live: bool) -> TurnRunner:
    if not live:
        return _StubRunner()
    try:
        return _LiveRunner()
    except Exception as exc:  # noqa: BLE001 — fall back loudly
        logger.warning("live runner unavailable (%s); falling back to stub", exc)
        return _StubRunner()


def _select_judge(live: bool) -> JudgeClient | None:
    """Build a judge for live runs. Stub runs never get a real judge."""
    if not live:
        return None
    judge = build_judge_from_env()
    if judge is None:
        logger.warning("no judge available; verdicts will read 'judge skipped'")
    return judge


class _StubRunner:
    """Deterministic fake that fills the trace without calling an LLM."""

    async def run(self, case: StressCase, *, user_id: str) -> TurnResult:
        del user_id
        return TurnResult(
            reply_body=f"[stub reply for {case.id}]",
            tools_called=(),
            backends_hit=(),
            latency_ms={"total_turn": 0},
            tokens={"input": 0, "output": 0, "total_cost_usd": 0.0},
            error=None,
        )


class _LiveRunner:
    """Fire the real ``donna_turn`` and translate its trace.

    Constructed lazily so importing this module doesn't require the SDK.
    """

    def __init__(self) -> None:
        from donna_runtime.config import DonnaAgentConfig
        from donna_runtime.runner import donna_turn

        self._config_factory = DonnaAgentConfig
        self._turn = donna_turn

    async def run(self, case: StressCase, *, user_id: str) -> TurnResult:
        config = self._config_factory(user_id=user_id, chat_already_persisted=False)
        t0 = time.time()
        try:
            trace = await self._turn(case.query, config)
        except Exception as exc:  # noqa: BLE001 — boundary catch
            return TurnResult(
                reply_body="",
                tools_called=(),
                backends_hit=(),
                latency_ms={"total_turn": int((time.time() - t0) * 1000)},
                tokens={},
                error=f"donna_turn raised: {exc!r}",
            )
        return TurnResult(
            reply_body=trace.result_text or "",
            tools_called=tuple(_tool_names(trace)),
            backends_hit=tuple(_backends_hit(trace)),
            latency_ms={"total_turn": trace.duration_ms},
            tokens={
                "input": int(trace.usage.get("input_tokens") or 0),
                "output": int(trace.usage.get("output_tokens") or 0),
                "cache_read": trace.cache_read_input_tokens,
                "cache_write": trace.cache_creation_input_tokens,
                "total_cost_usd": trace.total_cost_usd,
            },
            error=None,
        )


def _tool_names(trace: Any) -> list[str]:
    out: list[str] = []
    for call in getattr(trace, "tool_calls", []) or []:
        name = call.get("tool") if isinstance(call, dict) else None
        if name:
            out.append(str(name))
    return out


def _backends_hit(trace: Any) -> list[str]:
    """Infer which backends fired from the tool call list.

    Coarse mapping keyed on tool name prefix; refine once we wire real
    runs and can assert against ``RetrievalTrace.raw_hits_by_source``.
    """
    tool_to_backends = {
        "smart_recall": ("supermemory", "graphiti"),
        "recall": ("supermemory", "graphiti"),
        "list_observations": ("observations",),
        "list_open_loops": ("open_loops",),
        "list_calendar": ("calendar",),
        "check_calendar": ("calendar",),
        "read_situation_brief": ("living_profile",),
    }
    seen: list[str] = []
    for name in _tool_names(trace):
        for base, backends in tool_to_backends.items():
            if base in name:
                for backend in backends:
                    if backend not in seen:
                        seen.append(backend)
    return seen


if __name__ == "__main__":
    main()
