"""Proactive subsystem dry-run — no loop, no WhatsApp delivery.

Runs ``run_proactive_tick`` for one user and prints, in order:

  1. the ProactiveContext that was assembled (profile blurb, time)
  2. each ProactiveMove the reasoner emitted (with rationale)
  3. each move that was gated out (with reason)
  4. each move that was executed (with status + elapsed_ms)
  5. each judge verdict (send/silence + draft or reason)
  6. the final list of drafts that would have shipped

Two flags worth knowing:

- ``--no-exa``: skip the executor entirely. Useful when you want to see
  what Donna *wants* to look up without spending Exa credits.
- ``--reasoner-only``: just print the proactive moves Haiku emits. No
  gates, no execution, no judge. Cheapest mode.

Examples:

    # Full pipeline against a real user
    python scripts/proactive_dry_run.py --user-id u_abc

    # Reasoner only — see what Donna *would* search if let off the leash
    python scripts/proactive_dry_run.py --user-id u_abc --reasoner-only

    # Inject a synthetic profile blurb (no DB hit)
    python scripts/proactive_dry_run.py --profile-file /tmp/blurb.txt

    # Inject a recent thread snippet to anchor the reasoner
    python scripts/proactive_dry_run.py --user-id u_abc \\
        --thread "user: poke just shipped a new revision today"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env so EXA_API_KEY / ANTHROPIC_API_KEY / DATABASE_URL are populated
# the same way the rest of Donna's entry points see them.
from donna_runtime.env import load_dotenv

load_dotenv()

from backend.web.proactive.gates import CostBudget, InMemoryDedupStore, apply_gates
from backend.web.proactive.judge import judge_results
from backend.web.proactive.query_creation import create_proactive_moves
from backend.web.proactive.runner import build_context, run_proactive_tick
from backend.web.proactive.types import ProactiveContext


# ---------------------------------------------------------------------------
# tiny pretty printers (ANSI-free, copy-pasteable into a terminal log)
# ---------------------------------------------------------------------------


def _hr(label: str) -> str:
    return f"\n── {label} " + "─" * max(2, 70 - len(label) - 4)


def _print_context(ctx: ProactiveContext) -> None:
    print(_hr("PROACTIVE CONTEXT"))
    print(f"user_id:           {ctx.user_id}")
    print(f"current_datetime:  {ctx.current_datetime}")
    if ctx.last_proactive_at:
        print(f"last_proactive_at: {ctx.last_proactive_at}")
    if ctx.recent_thread.strip():
        print(f"\nrecent_thread:\n{_indent(ctx.recent_thread, 2)}")
    if ctx.profile_blurb.strip():
        print(f"\nprofile_blurb ({len(ctx.profile_blurb)} chars):")
        print(_indent(ctx.profile_blurb, 2))
    else:
        print("\n(profile blurb is empty)")


def _print_moves(moves) -> None:
    print(_hr(f"MOVES EMITTED ({len(moves)})"))
    if not moves:
        print("(reasoner returned 0 moves — silence)")
        return
    for i, m in enumerate(moves, start=1):
        print(f"\n[{i}] {m.tool.upper()}  urgency={m.urgency:.2f}  hint={m.render_hint}")
        print(f"    dedup_key:  {m.dedup_key}")
        print(f"    query:      {m.query}")
        if m.params:
            print(f"    params:     {json.dumps(m.params, ensure_ascii=False)}")
        print(f"    rationale:  {m.rationale}")


def _print_dropped(dropped) -> None:
    if not dropped:
        return
    print(_hr(f"GATED OUT ({len(dropped)})"))
    for d in dropped:
        print(f"  - {d.move.dedup_key} ({d.move.tool}): {d.reason}")


def _print_results(results) -> None:
    if not results:
        return
    print(_hr(f"EXECUTION RESULTS ({len(results)})"))
    for r in results:
        head = f"  - {r.move.dedup_key} {r.move.tool} → {r.status} ({r.elapsed_ms}ms)"
        if r.skipped_reason:
            head += f"  [{r.skipped_reason}]"
        print(head)
        if isinstance(r.payload, dict):
            inner = r.payload.get("results") if "results" in r.payload else r.payload
            if isinstance(inner, list):
                for j, item in enumerate(inner[:3], start=1):
                    url = item.get("url", "")
                    title = item.get("title", "") or url
                    print(f"      [{j}] {title[:90]}")
                    if url:
                        print(f"          {url}")


def _print_verdicts(verdicts) -> None:
    if not verdicts:
        return
    print(_hr(f"JUDGE VERDICTS ({len(verdicts)})"))
    for r, v in verdicts:
        if v.decision == "send":
            print(f"  ✓ SEND    {r.move.dedup_key}")
            print(f"    draft: {v.draft}")
        else:
            print(f"  · silence {r.move.dedup_key} — {v.reason}")


def _print_drafts(drafts) -> None:
    print(_hr("DRAFTS THAT WOULD SHIP"))
    if not drafts:
        print("(none — Donna stays silent this tick)")
        return
    for i, (r, draft) in enumerate(drafts, start=1):
        print(f"\n[{i}] from {r.move.dedup_key}")
        print(_indent(draft, 4))


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


# ---------------------------------------------------------------------------
# loaders / overrides
# ---------------------------------------------------------------------------


def _make_blurb_loader(args: argparse.Namespace):
    """Pick the right ContextLoader based on CLI flags."""
    if args.profile_file:
        text = Path(args.profile_file).read_text()

        async def from_file(_user_id: str) -> str:
            return text

        return from_file

    if args.profile is not None:
        text = args.profile

        async def from_arg(_user_id: str) -> str:
            return text

        return from_arg

    # Default: hit the real DB renderer.
    from backend.memory.user_facts.rendering import load_and_render

    async def from_db(user_id: str) -> str:
        return await load_and_render(user_id)

    return from_db


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------


async def _reasoner_only(args: argparse.Namespace) -> int:
    """Just call create_proactive_moves and print. No gates, no Exa, no judge."""
    loader = _make_blurb_loader(args)
    ctx = await build_context(
        args.user_id,
        recent_thread=args.thread,
        load_blurb=loader,
    )
    _print_context(ctx)
    moves = await create_proactive_moves(ctx, max_moves=args.max_moves)
    _print_moves(moves)
    return 0


async def _no_exa(args: argparse.Namespace) -> int:
    """Reasoner + gates only. Skip executor + judge."""
    loader = _make_blurb_loader(args)
    ctx = await build_context(
        args.user_id,
        recent_thread=args.thread,
        load_blurb=loader,
    )
    _print_context(ctx)
    moves = await create_proactive_moves(ctx, max_moves=args.max_moves)
    _print_moves(moves)
    if not moves:
        return 0
    ledger = InMemoryDedupStore()
    outcome = apply_gates(
        moves,
        user_id=args.user_id,
        ledger=ledger,
        budget=CostBudget(per_turn=args.max_moves),
    )
    _print_dropped(outcome.dropped)
    print(_hr(f"WOULD EXECUTE ({len(outcome.accepted)})"))
    for m in outcome.accepted:
        print(f"  - {m.tool} {m.dedup_key}: {m.query}")
    return 0


async def _full(args: argparse.Namespace) -> int:
    """Full pipeline: reason → gate → execute → judge."""
    loader = _make_blurb_loader(args)
    tick = await run_proactive_tick(
        user_id=args.user_id,
        recent_thread=args.thread,
        max_moves=args.max_moves,
        budget=CostBudget(per_turn=args.max_moves),
        load_blurb=loader,
    )
    # --json-only emits ONLY the structured trace (jq-pipeable). Otherwise
    # we print the human-readable trace, plus an optional JSON appendix.
    if args.json_only:
        print(json.dumps(_tick_to_json(tick), indent=2, default=str))
        return 0

    # Re-render the context for the trace (the runner doesn't expose it).
    ctx = await build_context(
        args.user_id,
        recent_thread=args.thread,
        load_blurb=loader,
    )
    _print_context(ctx)
    _print_moves(tick.moves_emitted)
    _print_dropped(tick.moves_dropped)
    _print_results(tick.results)
    _print_verdicts(tick.verdicts)
    _print_drafts(tick.drafts_to_send)
    print(f"\ntotal elapsed: {tick.elapsed_ms}ms")
    if args.json:
        print(_hr("RAW JSON"))
        print(json.dumps(_tick_to_json(tick), indent=2, default=str))
    return 0


def _tick_to_json(tick) -> dict:
    return {
        "user_id": tick.user_id,
        "moves_emitted": [asdict(m) for m in tick.moves_emitted],
        "moves_dropped": [
            {"move": asdict(d.move), "reason": d.reason} for d in tick.moves_dropped
        ],
        "results": [
            {
                "move": asdict(r.move),
                "status": r.status,
                "elapsed_ms": r.elapsed_ms,
                "skipped_reason": r.skipped_reason,
                "payload": r.payload,
            }
            for r in tick.results
        ],
        "verdicts": [
            {
                "dedup_key": r.move.dedup_key,
                "decision": v.decision,
                "draft": v.draft,
                "reason": v.reason,
            }
            for r, v in tick.verdicts
        ],
        "elapsed_ms": tick.elapsed_ms,
    }


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run the proactive search subsystem (no loop, no WA).",
    )
    parser.add_argument("--user-id", default="cli_dryrun_user")
    parser.add_argument(
        "--thread",
        default="",
        help="Synthetic recent-thread snippet to anchor the reasoner.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Inline profile blurb (overrides DB lookup).",
    )
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Path to a file containing the profile blurb.",
    )
    parser.add_argument("--max-moves", type=int, default=3)
    parser.add_argument(
        "--reasoner-only",
        action="store_true",
        help="Stop after create_proactive_moves. No Exa, no judge.",
    )
    parser.add_argument(
        "--no-exa",
        action="store_true",
        help="Reason + gate only. Skip execution + judge.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Append a raw JSON dump of the tick result.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Emit only the JSON tick result (jq-pipeable). Suppresses the trace.",
    )
    args = parser.parse_args()

    if args.reasoner_only and args.no_exa:
        parser.error("--reasoner-only and --no-exa are mutually exclusive.")

    if args.reasoner_only:
        return asyncio.run(_reasoner_only(args))
    if args.no_exa:
        return asyncio.run(_no_exa(args))
    return asyncio.run(_full(args))


if __name__ == "__main__":
    raise SystemExit(main())
