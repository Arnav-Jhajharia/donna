"""Three-day simulated arc against live Donna + full memory dump.

Runs ~30 realistic turns across a synthetic 3-day user arc, then dumps every
memory backend the user's writes could have touched: Postgres (9+ tables),
Supermemory (episodic + doc chunks), Graphiti / FalkorDB (nodes + edges),
bitemporal facts, Living Profile, Situation Brief.

Output: scripts/_out/three_day_arc_<ts>/
  - arc_report.md        (annotated narrative + per-turn tool-call summary)
  - postgres_dump.json   (every user-scoped row)
  - supermemory_dump.json
  - graph_dump.json      (FalkorDB nodes + edges)
  - living_profile.md    (rendered prompt block)
  - raw_traces.jsonl     (per-turn TurnTrace serialisation)

Gated behind DONNA_ARC=1 because it hits live model + live backends and costs
~$0.30-0.50 in tokens.

Run with:
    DONNA_ARC=1 .venv/bin/python scripts/three_day_arc.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlalchemy import select, text  # noqa: E402

from backend.memory.clients.graphiti import _safe_group_id, get_graphiti  # noqa: E402
from backend.memory.clients.supermemory import MemoryClient  # noqa: E402
from backend.memory.tools.read_situation_brief import read_situation_brief  # noqa: E402
from backend.memory.user_facts.rendering import load_and_render  # noqa: E402
from db.models import (  # noqa: E402
    CalendarEntry,
    ChatMessage,
    DonnaInstance,
    Fact,
    Observation,
    OpenLoop,
    ProceduralRule,
    RunTrace,
    User,
)
from db.session import async_session  # noqa: E402
from donna_runtime.config import DonnaAgentConfig  # noqa: E402
from donna_runtime.runner import donna_turn  # noqa: E402


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("three_day_arc")
logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
# Arc definition — 30 turns across 3 simulated days
# -----------------------------------------------------------------------------

Arc = list[tuple[int, str, str]]  # (day, hour_label, user_message)


def build_arc() -> Arc:
    return [
        # Day 1 — bootstrap + first emotional event
        (1, "09:00", "hey donna"),
        (1, "09:02", "i'm in singapore, asia/singapore timezone"),
        (1, "09:05", "i'm a backend engineer at a fintech, 4 years in. team of 6."),
        (1, "14:00", "i have a big demo on thursday with the cfo. nervous about it."),
        (1, "14:02", "remind me wed night to prep the slides"),
        (1, "16:30", "watch for anything about rate limits and api abuse on hacker news"),
        (1, "19:45", "just got yelled at by my manager for the metrics dashboard being slow. feel like shit."),
        (1, "21:10", "my gf priya is in london doing her masters at ucl"),
        (1, "21:12", "we're supposed to video call saturday 9pm my time"),
        (1, "22:00", "what do you know about me so far"),
        # Day 2 — continuity, updates, relationship context
        (2, "08:30", "morning"),
        (2, "08:45", "any thoughts on the demo prep?"),
        (2, "09:15", "how did i say i felt yesterday about the metrics thing"),
        (2, "11:00", "update: relocation came through, i'm moving to tokyo"),
        (2, "11:03", "also quit the fintech, joined a crypto startup as senior backend"),
        (2, "13:20", "remind me to close out my singapore bank accounts before i fly"),
        (2, "18:00", "did i tell you about priya?"),
        (2, "18:05", "she's actually moving to tokyo too in 2 weeks"),
        (2, "20:00", "close the demo loop, that's done. went well actually."),
        (2, "22:15", "mood check: tired but excited"),
        # Day 3 — recall + closure probes
        (3, "08:00", "hey"),
        (3, "08:10", "what timezone do you have for me"),
        (3, "08:11", "what was my timezone last week?"),
        (3, "09:00", "what's my current job"),
        (3, "10:30", "any open loops?"),
        (3, "12:00", "remember that stressful metrics moment from a few days ago?"),
        (3, "15:00", "what's my girlfriend's name"),
        (3, "15:02", "where is she right now"),
        (3, "20:00", "anything still unresolved for me"),
        (3, "22:00", "summary of everything you know about me"),
    ]


# -----------------------------------------------------------------------------
# User bootstrap
# -----------------------------------------------------------------------------

async def ensure_sandbox_user(user_id: str, timezone_name: str = "Asia/Singapore") -> None:
    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, phone, name, timezone, facts, onboarding_complete, "
                "has_google, is_sandbox, created_at) "
                "VALUES (:id, :phone, :name, :tz, '{}'::jsonb, "
                "false, false, true, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": user_id,
                "phone": f"+arc{abs(hash(user_id)) % 10_000_000_000:010d}",
                "name": "three-day arc user",
                "tz": timezone_name,
            },
        )
        await session.commit()


# -----------------------------------------------------------------------------
# Arc execution
# -----------------------------------------------------------------------------

def serialize_trace(trace) -> dict:
    def _coerce(v):
        if is_dataclass(v):
            return asdict(v)
        if isinstance(v, (list, tuple)):
            return [_coerce(x) for x in v]
        if isinstance(v, dict):
            return {k: _coerce(x) for k, x in v.items()}
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    out: dict = {}
    for attr in (
        "session_id",
        "reply",
        "error",
        "terminator",
        "outbound",
        "media_types",
        "model",
        "input_tokens",
        "output_tokens",
        "duration_ms",
    ):
        if hasattr(trace, attr):
            out[attr] = _coerce(getattr(trace, attr))
    if hasattr(trace, "tool_calls"):
        out["tool_calls"] = [
            {
                "tool": tc.get("tool") if isinstance(tc, dict) else getattr(tc, "tool", None),
                "inputs": _coerce(tc.get("inputs") if isinstance(tc, dict) else getattr(tc, "inputs", None)),
                "called_at_ms": tc.get("called_at_ms") if isinstance(tc, dict) else None,
                "duration_ms": tc.get("hook_duration_ms") if isinstance(tc, dict) else None,
            }
            for tc in trace.tool_calls
        ]
    for extra in ("result_text", "result_subtype", "result_is_error", "total_cost_usd",
                  "cache_creation_input_tokens", "cache_read_input_tokens", "num_turns",
                  "runtime_error"):
        if hasattr(trace, extra):
            out[extra] = _coerce(getattr(trace, extra))
    if hasattr(trace, "has_terminal_tool_call"):
        try:
            out["terminal_tool_ok"] = bool(trace.has_terminal_tool_call())
        except Exception:
            pass
    return out


async def run_arc(user_id: str, out_dir: Path) -> list[dict]:
    arc = build_arc()
    traces_path = out_dir / "raw_traces.jsonl"
    per_turn: list[dict] = []

    for i, (day, hour, message) in enumerate(arc, 1):
        logger.info(
            "turn %d/%d  day=%d  %s  msg=%s",
            i, len(arc), day, hour, message[:60],
        )
        cfg = DonnaAgentConfig(user_id=user_id, chat_already_persisted=False)
        t0 = time.perf_counter()
        try:
            trace = await donna_turn(message, config=cfg)
        except Exception as exc:
            logger.exception("turn %d crashed", i)
            per_turn.append({
                "turn": i,
                "day": day,
                "hour": hour,
                "message": message,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        row = {
            "turn": i,
            "day": day,
            "hour": hour,
            "message": message,
            "wall_ms": int((time.perf_counter() - t0) * 1000),
            "trace": serialize_trace(trace),
        }
        per_turn.append(row)
        with traces_path.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")

        await asyncio.sleep(0.5)

    return per_turn


# -----------------------------------------------------------------------------
# Post-arc dumps
# -----------------------------------------------------------------------------

async def dump_postgres(user_id: str) -> dict:
    dump: dict = {}
    models = [
        ("users", User, User.id == user_id),
        ("chat_messages", ChatMessage, ChatMessage.user_id == user_id),
        ("observations", Observation, Observation.user_id == user_id),
        ("open_loops", OpenLoop, OpenLoop.user_id == user_id),
        ("procedural_rules", ProceduralRule, ProceduralRule.user_id == user_id),
        ("facts_bitemporal", Fact, Fact.user_id == user_id),
        ("calendar_entries", CalendarEntry, CalendarEntry.user_id == user_id),
        ("donna_instances", DonnaInstance, DonnaInstance.user_id == user_id),
        ("run_traces", RunTrace, RunTrace.user_id == user_id),
    ]
    async with async_session() as session:
        for label, model, cond in models:
            rows = (await session.execute(select(model).where(cond))).scalars().all()
            dump[label] = [_row_to_dict(r) for r in rows]
    return dump


def _row_to_dict(row) -> dict:
    out: dict = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if isinstance(v, datetime):
            out[col.name] = v.isoformat()
        else:
            out[col.name] = v
    return out


async def dump_supermemory(user_id: str) -> dict:
    client = MemoryClient()
    dump = {"episodic": [], "document_chunks": [], "errors": []}
    probes = [
        "user profile and facts",
        "emotional moments and mood",
        "work and career",
        "relationships and people",
        "plans and schedule",
        "location and timezone",
    ]
    seen_ids: set[str] = set()
    for q in probes:
        try:
            hits = await client.search_with_graph(user_id, q, limit=50)
            for h in hits or []:
                hid = getattr(h, "id", None)
                if hid and hid in seen_ids:
                    continue
                if hid:
                    seen_ids.add(hid)
                dump["episodic"].append({
                    "id": getattr(h, "id", None),
                    "content": getattr(h, "content", None),
                    "score": getattr(h, "score", None),
                    "updated_at": getattr(h, "updated_at", None),
                    "metadata": getattr(h, "metadata", {}),
                    "relations": getattr(h, "relations", []),
                    "probe_query": q,
                })
        except Exception as exc:
            dump["errors"].append(f"episodic probe {q!r}: {type(exc).__name__}: {exc}")
        try:
            chunks = await client.search_document_chunks(user_id, q, limit=20)
            for c in chunks or []:
                dump["document_chunks"].append({
                    "content": getattr(c, "content", None),
                    "score": getattr(c, "score", None),
                    "doc_id": getattr(c, "doc_id", None),
                    "metadata": getattr(c, "metadata", {}),
                    "probe_query": q,
                })
        except Exception as exc:
            dump["errors"].append(f"doc probe {q!r}: {type(exc).__name__}: {exc}")
    return dump


async def dump_graphiti(user_id: str) -> dict:
    g = await get_graphiti()
    if g is None:
        return {"status": "degraded", "note": "graphiti init returned None"}
    from backend.memory.clients.graphiti import _route_to_user_db

    group_id = _safe_group_id(user_id)
    _route_to_user_db(g, group_id)

    dump: dict = {"group_id": group_id, "nodes": [], "edges": [], "errors": []}
    try:
        node_rows, _, _ = await g.driver.execute_query(
            "MATCH (n) RETURN n LIMIT 1000"
        )
        for rec in node_rows or []:
            node = rec.get("n") if isinstance(rec, dict) else None
            if node is not None:
                dump["nodes"].append(_falkor_to_dict(node))
    except Exception as exc:
        dump["errors"].append(f"nodes: {type(exc).__name__}: {exc}")

    try:
        edge_rows, _, _ = await g.driver.execute_query(
            "MATCH (a)-[r]->(b) "
            "RETURN type(r) AS type, properties(r) AS props, "
            "id(a) AS from_id, id(b) AS to_id, "
            "labels(a) AS from_labels, labels(b) AS to_labels LIMIT 2000"
        )
        for rec in edge_rows or []:
            if isinstance(rec, dict):
                dump["edges"].append({
                    "type": rec.get("type"),
                    "props": rec.get("props", {}),
                    "from_id": rec.get("from_id"),
                    "to_id": rec.get("to_id"),
                    "from_labels": rec.get("from_labels"),
                    "to_labels": rec.get("to_labels"),
                })
    except Exception as exc:
        dump["errors"].append(f"edges: {type(exc).__name__}: {exc}")

    return dump


def _falkor_to_dict(node) -> dict:
    # FalkorDB/graphiti wraps nodes variously — best effort to surface labels + props.
    out: dict = {}
    for attr in ("labels", "properties", "id"):
        if hasattr(node, attr):
            val = getattr(node, attr)
            out[attr] = val() if callable(val) else val
    if not out:
        out["repr"] = repr(node)[:400]
    return out


async def dump_situational_surface(user_id: str) -> dict:
    surface: dict = {}
    try:
        rendered = await load_and_render(user_id)
        surface["user_facts_rendered"] = rendered
    except Exception as exc:
        surface["user_facts_rendered_error"] = f"{type(exc).__name__}: {exc}"
    try:
        brief = await read_situation_brief(user_id=user_id)
        surface["situation_brief"] = brief
    except Exception as exc:
        surface["situation_brief_error"] = f"{type(exc).__name__}: {exc}"
    return surface


# -----------------------------------------------------------------------------
# Report writer
# -----------------------------------------------------------------------------

def write_markdown_report(
    out_dir: Path,
    user_id: str,
    per_turn: list[dict],
    pg: dict,
    sm: dict,
    graph: dict,
    surface: dict,
) -> Path:
    md = out_dir / "arc_report.md"
    lines: list[str] = []
    lines.append(f"# Three-Day Arc Report — {user_id}")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Turn-by-turn (what Donna did)")
    lines.append("")
    for row in per_turn:
        trace = row.get("trace", {})
        tool_names = [tc.get("name") for tc in trace.get("tool_calls", [])]
        reply = (trace.get("reply") or "").replace("\n", " ")[:180]
        terminator = trace.get("terminator") or "(none)"
        lines.append(
            f"- **Day {row['day']} {row['hour']}** — user: `{row['message'][:70]}`  \n"
            f"  tools: `{tool_names}`  \n"
            f"  terminator: `{terminator}`  \n"
            f"  reply: {reply or '(none)'}"
        )
        if row.get("error"):
            lines.append(f"  ERROR: {row['error']}")
    lines.append("")
    lines.append("## Postgres — counts by table")
    lines.append("")
    for table, rows in sorted(pg.items()):
        lines.append(f"- `{table}`: **{len(rows)}** rows")
    lines.append("")
    lines.append("## Supermemory")
    lines.append(f"- episodic hits (deduped): **{len(sm.get('episodic', []))}**")
    lines.append(f"- document chunks: **{len(sm.get('document_chunks', []))}**")
    if sm.get("errors"):
        lines.append("- errors:")
        for e in sm["errors"]:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append("## Graphiti / FalkorDB")
    lines.append(f"- group_id (FalkorDB database): `{graph.get('group_id')}`")
    lines.append(f"- nodes: **{len(graph.get('nodes', []))}**")
    lines.append(f"- edges: **{len(graph.get('edges', []))}**")
    if graph.get("errors"):
        lines.append("- errors:")
        for e in graph["errors"]:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append("## Rendered user-facts block (what appears in system prompt)")
    lines.append("")
    lines.append("```")
    lines.append(surface.get("user_facts_rendered", "(unavailable)"))
    lines.append("```")
    lines.append("")
    lines.append("## Situation brief (read_situation_brief payload)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(surface.get("situation_brief", {}), indent=2, default=str)[:6000])
    lines.append("```")
    md.write_text("\n".join(lines))
    return md


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

async def main() -> None:
    if os.getenv("DONNA_ARC") != "1":
        print("gated: set DONNA_ARC=1 to run (costs real tokens)")
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    user_id = f"three-day-arc-{ts}"
    out_dir = ROOT / "scripts" / "_out" / f"three_day_arc_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "user_id.txt").write_text(user_id + "\n")
    print(f"user_id: {user_id}")
    print(f"out_dir: {out_dir}")

    await ensure_sandbox_user(user_id)
    print("sandbox user seeded")

    print("running arc...")
    per_turn = await run_arc(user_id, out_dir)
    (out_dir / "per_turn.json").write_text(json.dumps(per_turn, indent=2, default=str))

    print("dumping postgres...")
    pg = await dump_postgres(user_id)
    (out_dir / "postgres_dump.json").write_text(json.dumps(pg, indent=2, default=str))

    print("dumping supermemory...")
    sm = await dump_supermemory(user_id)
    (out_dir / "supermemory_dump.json").write_text(json.dumps(sm, indent=2, default=str))

    print("dumping graphiti / falkordb...")
    graph = await dump_graphiti(user_id)
    (out_dir / "graph_dump.json").write_text(json.dumps(graph, indent=2, default=str))

    print("dumping living profile / situation brief...")
    surface = await dump_situational_surface(user_id)
    (out_dir / "living_profile.md").write_text(
        "# User Facts Rendered\n\n```\n"
        + (surface.get("user_facts_rendered") or "(none)")
        + "\n```\n\n# Situation Brief\n\n```json\n"
        + json.dumps(surface.get("situation_brief", {}), indent=2, default=str)
        + "\n```\n"
    )

    md = write_markdown_report(out_dir, user_id, per_turn, pg, sm, graph, surface)
    print(f"\nreport: {md}")
    print(f"all artifacts in: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
