"""Observability into how proactive web queries are generated.

Answers "how did Donna decide what to watch on the web for me?"

Three modes:

  default       Run a fresh derivation NOW against the user's current LP.
                Prints input signals + queries + angle analysis + cost.
                Costs ~few cents Anthropic. Writes a trace file.

  --trace       Read the latest persisted trace (from the last
                production tick) without running the deriver. Free.

  --no-call     Show the user_block (LP + chats + observations + ...)
                that WOULD be sent to the deriver without actually
                calling it. Free. Useful for understanding the input.

Usage:
    python scripts/query_gen_observe.py <user_id>
    python scripts/query_gen_observe.py <user_id> --trace
    python scripts/query_gen_observe.py <user_id> --no-call
    python scripts/query_gen_observe.py <user_id> --trace --list
        (list all traces for this user, newest first)

Traces live at ~/.donna/query_gen_traces/ — JSON files named
{user_id_prefix}_{ts}.json with the full input, queries, model,
duration, and any error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _hr() -> None:
    print("─" * 78)


def _trace_dir() -> Path:
    import os
    raw = os.environ.get("DONNA_QUERY_GEN_TRACE_DIR")
    if raw:
        return Path(raw)
    return Path.home() / ".donna" / "query_gen_traces"


def _list_traces(user_id: str) -> list[Path]:
    d = _trace_dir()
    if not d.exists():
        return []
    prefix = f"{user_id[:12]}_"
    return sorted(
        [p for p in d.iterdir() if p.name.startswith(prefix) and p.suffix == ".json"],
        reverse=True,
    )


def _print_user_block(block: str) -> None:
    """Pretty-print the user_block sections as the deriver sees them."""
    _hr()
    print("USER BLOCK (what the deriver actually saw)")
    _hr()
    print(f"  total: {len(block)} chars\n")
    sections = block.split("\n\n## ")
    for i, sec in enumerate(sections):
        if i == 0 and not sec.startswith("##"):
            sec = sec.lstrip("##").strip()
        else:
            sec = sec.strip()
        if not sec:
            continue
        first_line = sec.split("\n", 1)[0][:60]
        body = sec[len(first_line):].strip()
        chars = len(body)
        line_count = body.count("\n") + 1 if body else 0
        print(f"  ## {first_line}  ({chars} chars, {line_count} lines)")
    print()


def _print_queries(queries: list[dict]) -> None:
    _hr()
    print(f"QUERIES PRODUCED ({len(queries)})")
    _hr()
    by_angle: dict[str, list] = defaultdict(list)
    for q in queries:
        by_angle[q["angle"]].append(q)
    for angle in sorted(by_angle):
        items = by_angle[angle]
        print(f"\n  ── {angle.upper()} ({len(items)})")
        for q in items:
            sim = " +sim" if q.get("expand_with_similar") else ""
            print(f"    [{q['cadence']:8s}{sim:5s}] {q['text']}")
            if q.get("ties_to"):
                print(f"             ties_to: {q['ties_to'][:80]}")
    print()


def _print_fanout_analysis(queries: list[dict]) -> None:
    _hr()
    print("FANOUT ANALYSIS")
    _hr()
    if not queries:
        print("  no queries to analyze")
        print()
        return
    counts = Counter(q["angle"] for q in queries)
    cadences = Counter(q["cadence"] for q in queries)
    expand = sum(1 for q in queries if q.get("expand_with_similar"))

    print(f"  total queries:    {len(queries)}")
    print(f"  by angle:")
    REQUIRED_ANGLES = {"neighbor", "person", "rhythm"}
    for angle, n in counts.most_common():
        flag = " ✓" if angle in REQUIRED_ANGLES else ""
        bar = "█" * n
        print(f"    {angle:14s} {n:2d}  {bar}{flag}")

    missing_required = REQUIRED_ANGLES - set(counts.keys())
    if missing_required:
        print(f"\n  ⚠  missing required angle(s): {sorted(missing_required)}")
    else:
        print("\n  ✓  all required angles present (neighbor + person + rhythm)")

    print(f"\n  by cadence:")
    for cad in ("daily", "weekly", "monthly"):
        n = cadences.get(cad, 0)
        bar = "█" * n
        print(f"    {cad:10s} {n:2d}  {bar}")

    print(f"\n  expand_with_similar: {expand}/{len(queries)} ({expand*100//len(queries)}%)")

    # Fanout rule: max 3 queries on primary work domain
    work_domain_angles = {"direct", "problem"}
    work_count = sum(counts.get(a, 0) for a in work_domain_angles)
    if work_count > 3:
        print(f"\n  ⚠  fanout rule violation: {work_count} queries on direct+problem (work domain). "
              "Rule says max 3. Prompt may need tightening.")
    else:
        print(f"\n  ✓  fanout rule ok: {work_count}/3 queries on direct+problem (work domain)")

    # Cost estimate per cycle
    daily_calls = cadences.get("daily", 0) * 30  # per month
    weekly_calls = cadences.get("weekly", 0) * 4
    monthly_calls = cadences.get("monthly", 0) * 1
    total_calls = daily_calls + weekly_calls + monthly_calls
    # Each call: 1 search + 1 findSimilar (if expand=True) = up to 10 credits
    avg_per_call = 7.5  # ~75% expand
    monthly_credits = total_calls * avg_per_call
    print(f"\n  projected monthly cost: ~{int(monthly_credits)} credits "
          f"({total_calls} sub-fires/mo, avg ~{avg_per_call:.1f} credits each)")
    print()


async def _print_diff_vs_active(user_id: str, queries: list[dict]) -> None:
    """Compare the just-generated queries against the user's currently-active subs."""
    from sqlalchemy import select
    from backend.db.session import async_session
    from db.models import ProactiveSubscription

    _hr()
    print("DIFF vs current active subscriptions")
    _hr()
    async with async_session() as s:
        active = (await s.execute(
            select(ProactiveSubscription.description, ProactiveSubscription.cadence)
            .where(
                ProactiveSubscription.user_id == user_id,
                ProactiveSubscription.active.is_(True),
            )
        )).all()
    active_descs = {r[0] for r in active}
    new_descs = {q["text"] for q in queries}

    same = active_descs & new_descs
    new_only = new_descs - active_descs
    going_away = active_descs - new_descs

    print(f"  unchanged ({len(same)}):")
    for d in sorted(same):
        print(f"    = {d[:80]}")
    if new_only:
        print(f"\n  NEW ({len(new_only)}):")
        for d in sorted(new_only):
            print(f"    + {d[:80]}")
    if going_away:
        print(f"\n  WOULD DEACTIVATE ({len(going_away)}):")
        for d in sorted(going_away):
            print(f"    − {d[:80]}")
    if not new_only and not going_away:
        print("  (current active set is identical to what would be generated)")
    print()


def _print_trace_summary(trace: dict) -> None:
    _hr()
    print(f"TRACE  user={trace['user_id'][:12]}  ts={trace['ts'][:19]}  "
          f"model={trace['model']}  dur={trace['duration_ms']}ms")
    _hr()
    if trace.get("error"):
        print(f"  ERROR: {trace['error']}")
        print()
    print(f"  user_block: {trace['user_block_chars']} chars")
    print(f"  queries:    {trace['queries_count']}")
    print()


async def render_fresh(user_id: str, *, no_call: bool, max_queries: int) -> None:
    """Run a fresh derivation and pretty-print everything."""
    from backend.web.proactive.system_b.query_gen import (
        generate_ambitious_queries,
        _format_user_block,
    )
    # Show user_block first (always)
    if no_call:
        print("\n[--no-call mode: showing user_block only, no LLM call]\n")

    if no_call:
        # Manually rebuild the user_block to print it without calling Haiku.
        from sqlalchemy import select, desc as sa_desc
        from backend.db.session import async_session
        from db.models import ChatMessage, Observation, OpenLoop, User

        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if u is None:
                print(f"user not found: {user_id}")
                return
            profile = dict(u.living_profile or {})
            chat_rows = (await session.execute(
                select(ChatMessage.content)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.role == "user",
                    ChatMessage.is_shadow.is_(False),
                )
                .order_by(sa_desc(ChatMessage.created_at))
                .limit(200)
            )).all()
            recent_chats = [str(r[0] or "").strip() for r in chat_rows if r[0]]
            observations = []
            try:
                obs_rows = (await session.execute(
                    select(
                        Observation.type, Observation.raw,
                        Observation.fields, Observation.event_time,
                    )
                    .where(Observation.user_id == user_id)
                    .order_by(sa_desc(Observation.event_time))
                    .limit(20)
                )).all()
                for typ, raw, fields, _ in obs_rows:
                    rs = (raw or "").strip()
                    if rs:
                        observations.append(f"[{typ}] {rs}")
                        continue
                    fields_summary = ", ".join(f"{k}={v}" for k, v in (fields or {}).items() if v)
                    if fields_summary:
                        observations.append(f"[{typ}] {fields_summary}")
            except Exception as e:
                print(f"[obs fetch failed: {e}]")
            loop_rows = (await session.execute(
                select(OpenLoop.content)
                .where(OpenLoop.user_id == user_id, OpenLoop.status == "active")
                .order_by(sa_desc(OpenLoop.created_at))
                .limit(15)
            )).all()
            open_loops_text = [str(r[0] or "").strip() for r in loop_rows if r[0]]

        # Same durable_attentions logic as in query_gen.py
        durable_attentions = []
        try:
            from donna.attention.schema import AttentionStatus
            from donna.attention.store import AttentionStore
            store = AttentionStore()
            attentions = store.list(user_id=user_id)
            live_states = {AttentionStatus.LIVE, AttentionStatus.OFFERED}
            for a in attentions:
                if a.status not in live_states:
                    continue
                spec = getattr(a, "spec", None)
                if spec is None:
                    continue
                title = (getattr(spec, "title", "") or "").strip()
                subj_obj = getattr(spec, "subject", None)
                subj = (getattr(subj_obj, "name", "") or "").strip() if subj_obj else ""
                card = getattr(getattr(spec, "card", None), "value", "") or ""
                if title or subj:
                    bits = [b for b in (subj, title, f"({card})" if card else "") if b]
                    durable_attentions.append(" — ".join(bits))
        except Exception as e:
            print(f"durable_attentions load failed: {e}")

        block = _format_user_block(
            profile,
            recent_user_chats=recent_chats,
            observations=observations,
            open_loops=open_loops_text,
            durable_attentions=durable_attentions,
        )
        _print_user_block(block)
        print("(no queries generated; --no-call mode)")
        return

    # Real derivation
    print("running fresh derivation (Haiku call)...")
    queries = await generate_ambitious_queries(user_id, max_queries=max_queries)
    print(f"got {len(queries)} queries")
    print()

    # Convert to dict shape for printers
    q_dicts = [
        {
            "text": q.text,
            "angle": q.angle,
            "cadence": q.cadence,
            "ties_to": q.ties_to,
            "expand_with_similar": q.expand_with_similar,
        }
        for q in queries
    ]

    # Read the latest trace (which we just wrote) to get the user_block
    traces = _list_traces(user_id)
    if traces:
        latest = json.loads(traces[0].read_text())
        _print_user_block(latest.get("user_block", ""))

    _print_queries(q_dicts)
    _print_fanout_analysis(q_dicts)
    await _print_diff_vs_active(user_id, q_dicts)


def render_trace(user_id: str, *, list_only: bool) -> None:
    traces = _list_traces(user_id)
    if not traces:
        print(f"no traces found for user {user_id} at {_trace_dir()}")
        return
    if list_only:
        print(f"traces for user {user_id[:12]} ({len(traces)}):")
        for t in traces[:30]:
            try:
                d = json.loads(t.read_text())
                err = " ERROR" if d.get("error") else ""
                print(f"  {t.name}  {d['ts'][:19]}  q={d['queries_count']}  dur={d['duration_ms']}ms{err}")
            except Exception as e:
                print(f"  {t.name}  (unreadable: {e})")
        return

    latest = json.loads(traces[0].read_text())
    _print_trace_summary(latest)
    _print_user_block(latest.get("user_block", ""))
    _print_queries(latest.get("queries", []))
    _print_fanout_analysis(latest.get("queries", []))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id")
    parser.add_argument("--trace", action="store_true",
                        help="read latest persisted trace instead of running deriver")
    parser.add_argument("--list", action="store_true",
                        help="(with --trace) list all traces for this user")
    parser.add_argument("--no-call", action="store_true",
                        help="show user_block only, don't call Haiku")
    parser.add_argument("--max-queries", type=int, default=12)
    args = parser.parse_args()

    if args.trace:
        render_trace(args.user_id, list_only=args.list)
    else:
        await render_fresh(args.user_id, no_call=args.no_call, max_queries=args.max_queries)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
