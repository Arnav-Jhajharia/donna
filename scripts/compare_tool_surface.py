"""A/B comparison: verb-level vs mechanism-level tool surface.

Compares two smoke eval JSON outputs plus the correlated donna_traces.jsonl
entries and prints a single-table verdict.

Metrics isolated from voice-level confounders:
  - tool routing accuracy (did the right category fire?)
  - terminator compliance
  - tools per turn
  - cost per turn (from traces, matched by fixture order)
  - latency per turn (from traces, matched by fixture order)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Semantic equivalence: verb tool == the mechanism tools it wraps
VERB_WRAPS = {
    "recall": {
        "recall",
        "smart_recall",
        "recall_episodic",
        "recall_graph",
        "read_tracker",
        "list_open_loops",
        "list_observations",
        "read_situation_brief",
        "resolve_time_expression",
    },
    "remember": {
        "remember",
        "log_observation",
        "track_open_loop",
        "close_open_loop",
        "set_timezone",
    },
    "watch": {"watch", "create_attention"},
    "schedule": {"schedule", "schedule_reminder"},
    "check_calendar": {"check_calendar", "list_calendar"},
}


def strip_ns(name: str) -> str:
    return name.replace("mcp__donna__", "")


def canonical_category(tool_name: str) -> str:
    n = strip_ns(tool_name)
    for verb, members in VERB_WRAPS.items():
        if n in members:
            return verb
    return n


def load_eval(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def load_traces(path: Path) -> list[dict[str, Any]]:
    traces = []
    if not path.exists():
        return traces
    for line in path.read_text().splitlines():
        if line.strip():
            traces.append(json.loads(line))
    return traces


def match_traces(fixtures: list[dict[str, Any]], traces: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Match each fixture to its trace by user_message."""
    by_msg: dict[str, list[dict[str, Any]]] = {}
    for t in traces:
        msg = (t.get("user_message") or "").strip()
        by_msg.setdefault(msg, []).append(t)
    # sort each bucket by started_at for stable picking
    for k in by_msg:
        by_msg[k].sort(key=lambda t: t.get("started_at") or "")
    out: list[dict[str, Any] | None] = []
    used: dict[str, int] = {}
    # fixture ids map to messages via the loaded fixtures file; here we rely
    # on the eval output which doesn't carry the message. We approximate by
    # using the fixture id as a key into a static lookup.
    # Actually we don't have the message in the eval output. Fall back to
    # timestamp-sorted matching: nth fixture in order == nth trace post a
    # chosen cutoff.
    # Since we sort differently, do a simpler approach elsewhere.
    return out


def match_by_order(fixtures: list[dict[str, Any]], traces: list[dict[str, Any]], cutoff: str) -> list[dict[str, Any] | None]:
    """Take traces starting after `cutoff`, match in order to fixtures."""
    subset = [t for t in traces if (t.get("started_at") or "") >= cutoff]
    subset.sort(key=lambda t: t.get("started_at") or "")
    out: list[dict[str, Any] | None] = []
    for i, _ in enumerate(fixtures):
        out.append(subset[i] if i < len(subset) else None)
    return out


def score(eval_rows: list[dict[str, Any]], traces: list[dict[str, Any] | None]) -> dict[str, Any]:
    n = len(eval_rows)
    total_cost = 0.0
    total_dur = 0
    trace_matches = 0
    routing_ok = 0
    routing_tot = 0
    banned_hit = 0
    terminator_ok = 0
    tools_per_turn = 0
    voice_fail = 0
    pass_count = 0

    for r, t in zip(eval_rows, traces):
        if t is not None:
            trace_matches += 1
            total_cost += t.get("total_cost_usd") or 0
            total_dur += t.get("duration_ms") or 0
        calls = r.get("tool_calls") or []
        tools_per_turn += len(calls)
        if r.get("terminal_tool") == "send_burst":
            terminator_ok += 1
        if r.get("passed"):
            pass_count += 1

        # voice failure detection from reasons
        reasons = r.get("reasons") or []
        if any("banned phrase" in x or "reply too long" in x for x in reasons):
            voice_fail += 1

        # routing correctness (category-level, ignoring raw tool name)
        # we don't have expected_tools in the eval output, but we can infer
        # from reasons
        missing_expected = [x for x in reasons if "missing expected tool" in x]
        called_banned = [x for x in reasons if "called banned tool" in x]
        if missing_expected or called_banned:
            # route failure
            pass
        else:
            # no routing-related reason means routing was OK for this fixture
            # (either no expected_tools set, or all expected were called)
            routing_ok += 1
        routing_tot += 1
        banned_hit += len(called_banned)

    return {
        "n": n,
        "trace_matches": trace_matches,
        "pass_rate": pass_count / n if n else 0,
        "routing_ok_rate": routing_ok / routing_tot if routing_tot else 0,
        "terminator_rate": terminator_ok / n if n else 0,
        "avg_tools_per_turn": tools_per_turn / n if n else 0,
        "avg_cost_usd": total_cost / trace_matches if trace_matches else 0,
        "avg_dur_ms": total_dur / trace_matches if trace_matches else 0,
        "banned_tool_calls": banned_hit,
        "voice_failures": voice_fail,
        "pass_count": pass_count,
    }


def print_row(label: str, s: dict[str, Any]) -> None:
    print(f"{label:<14} n={s['n']:<3} pass={s['pass_count']:>2}/{s['n']:<2} "
          f"route={100*s['routing_ok_rate']:>5.1f}% "
          f"term={100*s['terminator_rate']:>5.1f}% "
          f"tools/turn={s['avg_tools_per_turn']:>4.2f} "
          f"${s['avg_cost_usd']:.4f}/turn "
          f"{s['avg_dur_ms']:>5.0f}ms "
          f"banned={s['banned_tool_calls']} "
          f"voice_fail={s['voice_failures']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", default="scripts/_out/current_prompt_smoke_full.json")
    parser.add_argument("--post", default="scripts/_out/verbs_smoke_full.json")
    parser.add_argument("--traces", default="donna_traces.jsonl")
    parser.add_argument("--pre-cutoff", default="2026-04-24T12:40")
    parser.add_argument("--post-cutoff", default="2026-04-24T20:00")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pre_rows = load_eval(root / args.pre)
    post_rows = load_eval(root / args.post) if (root / args.post).exists() else []
    traces = load_traces(root / args.traces)

    pre_traces = match_by_order(pre_rows, traces, args.pre_cutoff)
    post_traces = match_by_order(post_rows, traces, args.post_cutoff) if post_rows else []

    print("tool surface A/B — same fixtures, different tool registry")
    print("-" * 120)
    print_row("MECHANISM", score(pre_rows, pre_traces))
    if post_rows:
        print_row("VERB", score(post_rows, post_traces))
    else:
        print("VERB: no output file yet")
    print()
    print("trace file note: cost/latency are only meaningful when trace matches are near n.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
