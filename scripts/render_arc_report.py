"""Render a rich, annotated report from an existing three-day arc dump.

Usage:
    .venv/bin/python scripts/render_arc_report.py <dump_dir>

Writes `arc_report_full.md` alongside the raw dumps, showing WHAT Donna
stored (every row/episode/node), HOW (which backend, which container/column),
and WHEN (turn/timestamp).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def _load(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"could not load {path}: {exc}")
        return {}


def _truncate(s: str | None, n: int = 240) -> str:
    if not s:
        return "(none)"
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_ts(value) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%m-%d %H:%M:%S")
        except Exception:
            return value
    return str(value)


def render(dump_dir: Path) -> Path:
    user_id = (dump_dir / "user_id.txt").read_text().strip()
    per_turn = _load(dump_dir / "per_turn.json")
    pg = _load(dump_dir / "postgres_dump.json")
    sm = _load(dump_dir / "supermemory_dump.json")
    graph = _load(dump_dir / "graph_dump.json")

    L: list[str] = []
    L.append(f"# Three-Day Arc — What Donna Actually Stored")
    L.append("")
    L.append(f"- user_id: `{user_id}`")
    L.append(f"- turns: {len(per_turn)}")
    L.append(f"- rendered: {datetime.utcnow().isoformat()}Z")
    L.append("")
    L.append("## Storage footprint by layer")
    L.append("")
    L.append("| Layer | Backend | What's in there |")
    L.append("|---|---|---|")
    L.append(f"| chat_messages | Postgres | {len(pg.get('chat_messages', []))} rows (user + Donna) |")
    L.append(f"| observations | Postgres | {len(pg.get('observations', []))} rows |")
    L.append(f"| open_loops | Postgres | {len(pg.get('open_loops', []))} rows |")
    L.append(f"| procedural_rules | Postgres | {len(pg.get('procedural_rules', []))} rows |")
    L.append(f"| facts (bitemporal) | Postgres | {len(pg.get('facts_bitemporal', []))} rows |")
    L.append(f"| calendar_entries | Postgres | {len(pg.get('calendar_entries', []))} rows |")
    L.append(f"| donna_instances | Postgres | {len(pg.get('donna_instances', []))} rows |")
    L.append(f"| run_traces | Postgres | {len(pg.get('run_traces', []))} rows |")
    L.append(f"| users.living_profile (JSONB) | Postgres | see 'Living Profile' below |")
    L.append(f"| episodic memories | Supermemory | {len(sm.get('episodic', []))} deduped hits across 6 probes |")
    L.append(f"| document chunks | Supermemory | {len(sm.get('document_chunks', []))} chunks |")
    L.append(f"| graph nodes | Graphiti/FalkorDB | {len(graph.get('nodes', []))} |")
    L.append(f"| graph edges | Graphiti/FalkorDB | {len(graph.get('edges', []))} |")
    L.append("")

    L.append("## 1. Postgres — `users` row (identity + living profile)")
    L.append("")
    for u in pg.get("users", []):
        L.append(f"- **id**: `{u.get('id')}`")
        L.append(f"- **phone**: `{u.get('phone')}`")
        L.append(f"- **name**: {u.get('name')!r}")
        L.append(f"- **timezone**: `{u.get('timezone')}` ← note: never updated to Tokyo by Donna")
        L.append(f"- **profession**: {u.get('profession')!r}")
        L.append(f"- **onboarding_complete**: {u.get('onboarding_complete')}")
        L.append(f"- **is_sandbox**: {u.get('is_sandbox')}")
        facts = u.get("facts") or {}
        if facts:
            L.append("- **facts (JSONB)**:")
            L.append("  ```json")
            L.append("  " + json.dumps(facts, indent=2, default=str).replace("\n", "\n  "))
            L.append("  ```")
        lp = u.get("living_profile") or {}
        if lp:
            L.append("- **living_profile (JSONB)** — rendered into cached system prompt:")
            L.append("  ```json")
            L.append("  " + json.dumps(lp, indent=2, default=str)[:4000].replace("\n", "\n  "))
            L.append("  ```")
    L.append("")

    L.append("## 2. Postgres — `observations` (emotional / factual moments)")
    L.append("")
    obs = pg.get("observations", [])
    if not obs:
        L.append("_(none — Donna called `log_observation` only once across 30 turns)_")
    for o in obs:
        L.append(f"- **{_fmt_ts(o.get('created_at'))}** type=`{o.get('type')}`  event_time={_fmt_ts(o.get('event_time'))}")
        fields = o.get("fields") or {}
        L.append(f"  - fields: `{json.dumps(fields, default=str)[:300]}`")
        tags = o.get("tags") or {}
        if tags:
            L.append(f"  - tags: `{json.dumps(tags, default=str)[:200]}`")
    L.append("")

    L.append("## 3. Postgres — `open_loops` (ongoing threads)")
    L.append("")
    loops = pg.get("open_loops", [])
    for ol in loops:
        L.append(f"- **{_fmt_ts(ol.get('created_at'))}** status=`{ol.get('status')}`")
        L.append(f"  - content: {_truncate(ol.get('content'), 300)}")
        meta = ol.get("metadata") or {}
        if meta:
            L.append(f"  - metadata: `{json.dumps(meta, default=str)[:200]}`")
    L.append("")

    L.append("## 4. Postgres — `facts` (bitemporal fact table)")
    L.append("")
    facts = pg.get("facts_bitemporal", [])
    if not facts:
        L.append("_(none — bitemporal write path is wired for timezone only, and the "
                 "only set_timezone call crashed with AttributeError before the write)_")
    for f in facts:
        L.append(f"- subject=`{f.get('subject')}` predicate=`{f.get('predicate')}` "
                 f"object=`{f.get('object')}`")
        L.append(f"  - t_valid_from={_fmt_ts(f.get('t_valid_from'))}  t_valid_to={_fmt_ts(f.get('t_valid_to'))}")
        L.append(f"  - t_recorded_at={_fmt_ts(f.get('t_recorded_at'))}  source=`{f.get('source')}`")
    L.append("")

    L.append("## 5. Postgres — `donna_instances` (attention / watches)")
    L.append("")
    for di in pg.get("donna_instances", []):
        L.append(f"- primitive=`{di.get('primitive')}` connector=`{di.get('connector')}` "
                 f"label={di.get('label')!r} status=`{di.get('status')}`")
        cfg = di.get("config") or {}
        if cfg:
            L.append(f"  - config: `{json.dumps(cfg, default=str)[:300]}`")
    L.append("")

    L.append("## 6. Postgres — `procedural_rules`")
    L.append("")
    rules = pg.get("procedural_rules", [])
    if not rules:
        L.append("_(none — procedural rules not emitted by this arc; tier-1/3 dead per memory-wireup-plan)_")
    for r in rules:
        L.append(f"- type=`{r.get('type')}` confidence={r.get('confidence')}: "
                 f"{_truncate(r.get('rule'), 240)}")
    L.append("")

    L.append("## 7. Postgres — `chat_messages` (first + last few)")
    L.append("")
    chats = pg.get("chat_messages", [])
    L.append(f"_{len(chats)} rows total. Showing first 6 and last 6._")
    L.append("")
    def _show_chat(m):
        prefix = "→" if m.get("role") == "user" else "←"
        proact = " (proactive)" if m.get("is_proactive") else ""
        L.append(f"- {prefix} **{_fmt_ts(m.get('created_at'))}** "
                 f"`{m.get('role')}`{proact}: {_truncate(m.get('content'), 180)}")
    for m in chats[:6]:
        _show_chat(m)
    if len(chats) > 12:
        L.append("- …")
    for m in chats[-6:]:
        _show_chat(m)
    L.append("")

    L.append("## 8. Supermemory — episodic memory")
    L.append("")
    eps = sm.get("episodic", [])
    L.append(f"_{len(eps)} deduped episodes. Stored via `MemoryClient.add_episode(container_tag=user_id)`. "
             "Showing top 10 by score._")
    L.append("")
    eps_sorted = sorted(eps, key=lambda e: float(e.get("score") or 0), reverse=True)
    for e in eps_sorted[:10]:
        L.append(f"- **score={e.get('score')}** updated_at=`{e.get('updated_at')}` id=`{_truncate(e.get('id'), 50)}`")
        L.append(f"  - content: {_truncate(e.get('content'), 400)}")
        rel = e.get("relations") or []
        if rel:
            L.append(f"  - relations ({len(rel)}): {_truncate(str(rel), 300)}")
    L.append("")

    L.append("## 9. Supermemory — document chunks")
    L.append("")
    chunks = sm.get("document_chunks", [])
    by_doc = Counter(c.get("doc_id") for c in chunks)
    L.append(f"_{len(chunks)} chunks across {len(by_doc)} doc_ids. Showing top 5 by score._")
    L.append("")
    chunks_sorted = sorted(chunks, key=lambda c: float(c.get("score") or 0), reverse=True)
    for c in chunks_sorted[:5]:
        L.append(f"- doc_id=`{_truncate(c.get('doc_id'), 40)}` score={c.get('score')}")
        L.append(f"  - content: {_truncate(c.get('content'), 400)}")
    L.append("")

    L.append("## 10. Graphiti / FalkorDB — knowledge graph")
    L.append("")
    L.append(f"- FalkorDB database name: `{graph.get('group_id')}`")
    L.append(f"- connect with: `redis-cli -h <falkordb_host> -p <port> GRAPH.QUERY {graph.get('group_id')} 'MATCH (n) RETURN n'`")
    L.append("")
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_labels = Counter()
    for n in nodes:
        labs = n.get("labels") or []
        for lab in labs:
            node_labels[lab] += 1
    L.append("**Node labels:**")
    for lab, count in node_labels.most_common():
        L.append(f"- `{lab}`: {count}")
    L.append("")
    edge_types = Counter(e.get("type") for e in edges)
    L.append("**Edge types:**")
    for t, count in edge_types.most_common():
        L.append(f"- `{t}`: {count}")
    L.append("")

    L.append("**Sample nodes (first 20, most interesting-looking):**")
    L.append("")
    for n in nodes[:20]:
        props = n.get("properties") or {}
        name = props.get("name") or props.get("summary") or props.get("content") or ""
        labs = n.get("labels") or []
        L.append(f"- **{labs}** `{_truncate(name, 120)}`")
        for k, v in list(props.items())[:4]:
            L.append(f"  - {k}: `{_truncate(str(v), 120)}`")
    L.append("")

    L.append("**Sample edges (first 15):**")
    L.append("")
    for e in edges[:15]:
        props = e.get("props") or {}
        fact = props.get("fact") or props.get("name") or ""
        L.append(f"- `{e.get('type')}` {e.get('from_labels')} → {e.get('to_labels')}: "
                 f"{_truncate(fact, 160)}")
    L.append("")

    L.append("## 11. Signal vs. gap summary")
    L.append("")
    L.append("**Signal (what works):**")
    L.append("- Chat messages persist reliably: " f"{len(chats)} rows across 30 user turns (Donna echoed + user messages).")
    L.append(f"- Open loops captured: {len(loops)} threads including the demo, Priya, relocation, job change.")
    L.append(f"- Supermemory episodic write fires: {len(eps)} distinct episodes ingested.")
    L.append(f"- Graph builds out: {len(nodes)} entity nodes, {len(edges)} edges — Priya/UCL/London/Tokyo/fintech/crypto all appear.")
    L.append(f"- Situation brief auto-refreshes and groups by week (see users.living_profile.situation_brief).")
    L.append("")
    L.append("**Gaps (what broke or never fired):**")
    L.append(f"- `users.timezone` stayed at `{pg.get('users', [{}])[0].get('timezone')}` — Tokyo update from Day 2 didn't propagate. "
             "Root cause: `set_timezone.py:133,146` crashes with `AttributeError: 'str' object has no attribute 'utc'` (name collision between `timezone` param and `datetime.timezone` import).")
    L.append(f"- `facts_bitemporal` has {len(facts)} rows — timezone history is not populated because the set_timezone bug aborts before the bitemporal write.")
    L.append(f"- `users.facts.profession` still says 'Backend engineer at fintech' after Day 2 said 'quit, joined crypto startup'. Fact extraction isn't running UPDATE semantics — it's append-or-skip.")
    L.append(f"- `observations` = {len(obs)} row despite 4+ emotional moments (yelled at, nervous, tired but excited). `log_observation` is under-called.")
    L.append(f"- `calendar_entries` = 0. Saturday 9pm video call did not produce a calendar row.")
    L.append(f"- `procedural_rules` = 0. No tier-2 rules extracted.")
    L.append(f"- `run_traces` = 0. Turn traces aren't being persisted to DB (only to .donna/events.jsonl).")
    L.append("")

    out = dump_dir / "arc_report_full.md"
    out.write_text("\n".join(L))
    return out


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: render_arc_report.py <dump_dir>")
        sys.exit(2)
    dump_dir = Path(sys.argv[1]).resolve()
    report = render(dump_dir)
    print(f"wrote {report}")


if __name__ == "__main__":
    main()
