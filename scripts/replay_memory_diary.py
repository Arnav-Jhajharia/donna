from __future__ import annotations

"""Replay a timestamped multi-day "user diary" into the DB, then evaluate memory.

This is a pragmatic test harness for "situational awareness":
  - seed chat_messages / observations / open_loops / schedules across many days
  - (optional) ingest matching episodes into Supermemory + Graphiti with timestamps
  - regenerate the stored temporal situation brief at a chosen "now"
  - run retrieval tools and dump a report (JSON) you can inspect

Typical run:
  python scripts/replay_memory_diary.py --days 12 --timezone Asia/Singapore

Live providers:
  - Supermemory: set SUPERMEMORY_API_KEY to ingest/recall episodic
  - Graphiti/FalkorDB: set FALKORDB_* + ANTHROPIC_API_KEY (and graphiti_core installed)
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_naive(dt: datetime) -> datetime:
    """DB stores naive UTC datetimes; normalize accordingly."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(tzinfo=None)


def _local(now_utc: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return now_utc.astimezone(tz)


@dataclass(frozen=True)
class DiaryTurn:
    days_ago: int
    local_hhmm: tuple[int, int]
    inbound: str
    outbound: list[str]


def _build_default_diary(days: int) -> list[DiaryTurn]:
    """High-signal multi-day timeline that should exercise last_week/this_week/next_week."""
    # Keep this compact so it doesn't spam Supermemory/Graphiti.
    # days_ago is relative to --now in local timezone.
    turns: list[DiaryTurn] = [
        DiaryTurn(
            days_ago=min(days - 1, 11),
            local_hhmm=(9, 10),
            inbound="i moved to tokyo for grad school. classes start next monday.",
            outbound=["noted. i can help you plan the move and the first week of school."],
        ),
        DiaryTurn(
            days_ago=min(days - 1, 9),
            local_hhmm=(8, 40),
            inbound="coffee was 6 bucks today.",
            outbound=["got it. do you want me to track coffee spend going forward?"],
        ),
        DiaryTurn(
            days_ago=min(days - 1, 8),
            local_hhmm=(21, 5),
            inbound="i need to finish visa paperwork by friday.",
            outbound=["ok. i will keep that as an open thread so it doesn't slip."],
        ),
        DiaryTurn(
            days_ago=min(days - 1, 6),
            local_hhmm=(12, 15),
            inbound="this week i need to ship the donna memory pipeline.",
            outbound=["makes sense. what are the top 3 deliverables for that this week?"],
        ),
        DiaryTurn(
            days_ago=min(days - 1, 4),
            local_hhmm=(7, 55),
            inbound="i slept 6 hours last night and feel a bit fried.",
            outbound=["noted. do you want to track sleep for a week to see a pattern?"],
        ),
        DiaryTurn(
            days_ago=min(days - 1, 2),
            local_hhmm=(10, 5),
            inbound="next week i have investor calls tuesday and thursday.",
            outbound=["ok. want reminders the morning of each call?"],
        ),
        DiaryTurn(
            days_ago=0,
            local_hhmm=(11, 30),
            inbound="what should i be focused on today?",
            outbound=["here's a quick focus list based on your current week and open threads."],
        ),
    ]
    # If the requested span is shorter, clamp days_ago above already.
    return turns


async def _seed_user(user_id: str, tz_name: str) -> None:
    from sqlalchemy import text

    from backend.db.session import async_session

    async with async_session() as session:
        # Insert with raw SQL so any NOT NULL columns with defaults remain valid.
        await session.execute(
            text(
                "INSERT INTO users (id, phone, name, timezone, facts, onboarding_complete, has_google, created_at) "
                "VALUES (:id, :phone, :name, :tz, '{}'::jsonb, false, false, now())"
            ),
            {
                "id": user_id,
                "phone": f"+diary{user_id[-10:]}",
                "name": "Diary Tester",
                "tz": tz_name,
            },
        )
        await session.commit()


async def _ensure_instances(user_id: str) -> dict[str, str]:
    """Create one DonnaInstance per observation type we seed, return instance_id mapping."""
    from sqlalchemy import select

    from backend.db.models import DonnaInstance
    from backend.db.session import async_session

    wanted = {
        "expense": ("track", "whatsapp_manual", "expenses", {"type": "expense"}),
        "mood": ("track", "whatsapp_manual", "mood", {"type": "mood"}),
        "sleep": ("track", "whatsapp_manual", "sleep", {"type": "sleep"}),
    }

    async with async_session() as session:
        existing = (
            await session.execute(select(DonnaInstance).where(DonnaInstance.user_id == user_id))
        ).scalars().all()
        by_type: dict[str, DonnaInstance] = {}
        for inst in existing:
            t = (inst.config or {}).get("type")
            if isinstance(t, str):
                by_type[t] = inst

        created: dict[str, str] = {}
        for obs_type, (primitive, connector, label, config) in wanted.items():
            inst = by_type.get(obs_type)
            if inst is None:
                inst = DonnaInstance(
                    user_id=user_id,
                    primitive=primitive,
                    connector=connector,
                    label=label,
                    config=config,
                    status="active",
                )
                session.add(inst)
                await session.flush()
            created[obs_type] = inst.id
        await session.commit()
        return created


async def _seed_chat_messages(user_id: str, now_utc: datetime, tz_name: str, turns: list[DiaryTurn]) -> list[dict]:
    from backend.db.models import ChatMessage
    from backend.db.session import async_session

    local_now = _local(now_utc, tz_name)
    seeded: list[dict] = []

    async with async_session() as session:
        for turn in turns:
            hh, mm = turn.local_hhmm
            local_time = (local_now - timedelta(days=turn.days_ago)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            created_at = _utc_naive(local_time)
            # Inbound
            session.add(
                ChatMessage(
                    user_id=user_id,
                    role="user",
                    content=turn.inbound,
                    created_at=created_at,
                )
            )
            # Outbound (space out by seconds so ordering is stable)
            for i, msg in enumerate(turn.outbound):
                session.add(
                    ChatMessage(
                        user_id=user_id,
                        role="assistant",
                        content=msg,
                        created_at=created_at + timedelta(seconds=5 + i),
                    )
                )
            seeded.append(
                {
                    "days_ago": turn.days_ago,
                    "local_time": local_time.isoformat(timespec="minutes"),
                    "created_at_utc": created_at.isoformat(timespec="seconds"),
                    "inbound": turn.inbound,
                    "outbound": turn.outbound,
                }
            )
        await session.commit()

    return seeded


async def _seed_open_loops(user_id: str, now_utc: datetime, tz_name: str) -> list[dict]:
    from backend.db.models import OpenLoop
    from backend.db.session import async_session

    local_now = _local(now_utc, tz_name)
    loops = [
        {
            "days_ago": 8,
            "local_time": (local_now - timedelta(days=8)).replace(hour=21, minute=6, second=0, microsecond=0),
            "content": "finish visa paperwork by friday",
            "status": "active",
        },
        {
            "days_ago": 1,
            "local_time": (local_now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0),
            "content": "buy a universal adapter for tokyo",
            "status": "closed",
        },
    ]

    seeded: list[dict] = []
    async with async_session() as session:
        for row in loops:
            created_at = _utc_naive(row["local_time"])
            status = row["status"]
            resolved_at = None
            if status == "closed":
                resolved_at = created_at + timedelta(hours=2)
            session.add(
                OpenLoop(
                    user_id=user_id,
                    content=row["content"],
                    source_message=None,
                    created_at=created_at,
                    status=status,
                    resolved_at=resolved_at,
                )
            )
            seeded.append(
                {
                    "days_ago": row["days_ago"],
                    "local_time": row["local_time"].isoformat(timespec="minutes"),
                    "created_at_utc": created_at.isoformat(timespec="seconds"),
                    "content": row["content"],
                    "status": status,
                }
            )
        await session.commit()
    return seeded


async def _seed_observations(
    user_id: str,
    now_utc: datetime,
    tz_name: str,
    instance_ids: dict[str, str],
) -> list[dict]:
    from backend.db.models import Observation
    from backend.db.session import async_session

    local_now = _local(now_utc, tz_name)

    samples = [
        # coffee expenses last week and this week
        ("expense", 9, (8, 45), {"category": "coffee", "amount": 6.0, "currency": "USD"}, {"merchant": "random cafe"}),
        ("expense", 7, (9, 5), {"category": "coffee", "amount": 6.0, "currency": "USD"}, {"merchant": "random cafe"}),
        ("expense", 2, (9, 0), {"category": "coffee", "amount": 5.5, "currency": "USD"}, {"merchant": "random cafe"}),
        # mood + sleep
        ("mood", 4, (20, 30), {"score": 7, "note": "excited but stressed"}, {}),
        ("sleep", 4, (8, 0), {"hours": 6.0, "quality": "poor"}, {}),
    ]

    seeded: list[dict] = []
    async with async_session() as session:
        for obs_type, days_ago, (hh, mm), fields, tags in samples:
            local_time = (local_now - timedelta(days=days_ago)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            event_time = _utc_naive(local_time)
            session.add(
                Observation(
                    user_id=user_id,
                    instance_id=instance_ids[obs_type],
                    type=obs_type,
                    event_time=event_time,
                    fields=fields,
                    tags=tags | {"source": "diary"},
                    raw=None,
                    confidence=1.0,
                    source="diary",
                    created_at=_utc_naive(datetime.now(UTC)),
                )
            )
            seeded.append(
                {
                    "type": obs_type,
                    "days_ago": days_ago,
                    "local_time": local_time.isoformat(timespec="minutes"),
                    "event_time_utc": event_time.isoformat(timespec="seconds"),
                    "fields": fields,
                    "tags": tags,
                }
            )
        await session.commit()
    return seeded


async def _seed_schedules(user_id: str, now_utc: datetime, tz_name: str) -> list[dict]:
    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session

    local_now = _local(now_utc, tz_name)
    # A next-week-ish schedule so it can appear in "next week" evidence.
    fire_local = (local_now + timedelta(days=5)).replace(hour=9, minute=0, second=0, microsecond=0)
    fire_at = _utc_naive(fire_local)
    seeded = {
        "fire_at_local": fire_local.isoformat(timespec="minutes"),
        "fire_at_utc": fire_at.isoformat(timespec="seconds"),
        "context": {"text": "investor call reminder", "source": "diary"},
    }
    async with async_session() as session:
        session.add(
            DonnaSchedule(
                user_id=user_id,
                phone=f"+diary{user_id[-10:]}",
                fire_at=fire_at,
                origin="user",
                context=seeded["context"],
                fired=False,
                status="pending",
                attempts=0,
                max_attempts=3,
                created_at=_utc_naive(datetime.now(UTC)),
            )
        )
        await session.commit()
    return [seeded]


async def _write_user_facts(user_id: str) -> dict[str, Any]:
    from backend.memory.user_facts.api import update_user_fact
    from backend.memory.user_facts.schema import Confidence, FactKey, Source

    # Keep minimal: enough to make the USER MODEL block non-empty.
    await update_user_fact(
        user_id=user_id,
        key=FactKey.HOME_CITY.value,
        value="Tokyo",
        source=Source.CONVERSATION_EXTRACTED,
        confidence=Confidence.HIGH,
    )
    await update_user_fact(
        user_id=user_id,
        key=FactKey.CURRENT_TIMEZONE.value,
        value="Asia/Tokyo",
        source=Source.CONVERSATION_INFERRED,
        confidence=Confidence.MEDIUM,
    )
    return {"home_city": "Tokyo", "current_timezone": "Asia/Tokyo"}


async def _ingest_external_episodes(
    user_id: str,
    seeded_turns: list[dict],
    *,
    ingest_supermemory: bool,
    ingest_graphiti: bool,
    max_episodes: int,
) -> dict[str, Any]:
    """Best-effort external ingestion aligned to the seeded timestamps."""
    report: dict[str, Any] = {"supermemory": {"attempted": 0, "ok": 0}, "graphiti": {"attempted": 0, "ok": 0}}

    # 1) Supermemory: store the episode body and include a timestamp hint in metadata.
    if ingest_supermemory:
        from backend.memory.clients.supermemory import get_memory_client

        client = get_memory_client()
        if client.available:
            for row in seeded_turns[:max_episodes]:
                report["supermemory"]["attempted"] += 1
                body = "USER: " + row["inbound"] + "\n" + "\n".join(f"DONNA: {m}" for m in row["outbound"])
                meta = {"at_utc": row["created_at_utc"], "source": "diary_harness"}
                episode_id = await client.add_episode(user_id=user_id, content=body, metadata=meta)
                if episode_id:
                    report["supermemory"]["ok"] += 1
        else:
            report["supermemory"]["degraded"] = True

    # 2) Graphiti: ingest with reference_time = seeded timestamp (real time semantics).
    if ingest_graphiti:
        from backend.memory.clients import graphiti as graphiti_client

        for row in seeded_turns[:max_episodes]:
            report["graphiti"]["attempted"] += 1
            ref = datetime.fromisoformat(row["created_at_utc"]).replace(tzinfo=UTC)
            body = "USER: " + row["inbound"] + "\n" + "\n".join(f"DONNA: {m}" for m in row["outbound"])
            ok = await graphiti_client.ingest_episode(user_id=user_id, content=body, reference_time=ref)
            if ok:
                report["graphiti"]["ok"] += 1

    return report


async def _evaluate(user_id: str, now_utc: datetime, tz_name: str, *, use_claude: bool) -> dict[str, Any]:
    from backend.memory.synthesis.temporal_brief import BriefImplementation, collect_temporal_evidence, synthesize_and_store_temporal_brief
    from backend.memory.tools.list_observations import list_observations
    from backend.memory.tools.list_open_loops import list_open_loops
    from backend.memory.tools.read_situation_brief import read_situation_brief
    from backend.memory.tools.recall_chat_thread import recall_chat_thread
    from backend.memory.tools.recall_document_chunks import recall_document_chunks
    from backend.memory.tools.recall_episodic import recall_episodic
    from backend.memory.tools.recall_graph import recall_graph
    from backend.memory.tools.smart_recall import smart_recall
    from backend.memory.user_facts.rendering import load_and_render
    from donna_runtime.context_builder import render_turn_context

    # 1) Store the situation brief at the chosen "now" so the USER MODEL block matches the timeline.
    brief = await synthesize_and_store_temporal_brief(
        user_id=user_id,
        implementation=BriefImplementation.WINDOWED_TIMELINE,
        now=now_utc,
        use_claude=use_claude,
    )

    # 2) Pull evidence and run tool retrievals to show what "all memory types" returns.
    evidence = await collect_temporal_evidence(user_id, now=now_utc)

    # A few representative retrieval calls (all degrade gracefully).
    obs_last_week = await list_observations(user_id=user_id, type="expense", period="last_week", limit=20)
    obs_this_week = await list_observations(user_id=user_id, type="expense", period="this_week", limit=20)
    loops = await list_open_loops(user_id=user_id, status="active", limit=10)
    situation = await read_situation_brief(user_id=user_id)
    chat = await recall_chat_thread(user_id=user_id, limit=12)
    smart = await smart_recall(user_id=user_id, message="coffee spend", top_k=5)
    episodic = await recall_episodic(user_id=user_id, query="tokyo coffee visa", limit=5)
    graph = await recall_graph(user_id=user_id, query="tokyo coffee visa", limit=5)
    docs = await recall_document_chunks(user_id=user_id, query="tokyo", limit=3)

    # 3) What the agent sees at turn start (volatile-only runtime context + cached user model block).
    user_model_block = await load_and_render(user_id)
    runtime_context = await render_turn_context(
        {
            "user_id": user_id,
            "_user_name": "Diary Tester",
            "_user_timezone": tz_name,
            "_is_first_message": False,
            "_resume_session_id": "fake-session-for-diary-harness",
        }
    )

    return {
        "now_utc": now_utc.isoformat(timespec="seconds"),
        "timezone": tz_name,
        "stored_brief": {"implementation": brief.implementation, "rendered": brief.render()},
        "evidence_counts": {
            "chat_messages": len(evidence.chat_messages),
            "observations": len(evidence.observations),
            "open_loops": len(evidence.open_loops),
            "schedules": len(evidence.schedules),
            "calendar": len(evidence.calendar),
        },
        "tool_reads": {
            "list_observations_last_week": obs_last_week,
            "list_observations_this_week": obs_this_week,
            "list_open_loops_active": loops,
            "read_situation_brief": situation,
            "recall_chat_thread": chat,
            "smart_recall": smart,
            "recall_episodic": episodic,
            "recall_graph": graph,
            "recall_document_chunks": docs,
        },
        "prompt_views": {
            "user_model_block": user_model_block,
            "runtime_context": runtime_context,
        },
    }


async def _cleanup(user_id: str) -> None:
    try:
        from sqlalchemy import delete

        from backend.db.models import ChatMessage, DonnaInstance, DonnaSchedule, Observation, OpenLoop, User
        from backend.db.session import async_session
    except Exception:
        return

    try:
        async with async_session() as session:
            for model in (ChatMessage, Observation, OpenLoop, DonnaSchedule):
                await session.execute(delete(model).where(model.user_id == user_id))
            await session.execute(delete(DonnaInstance).where(DonnaInstance.user_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
    except Exception:
        # Never allow cleanup errors to mask the evaluation failure.
        return


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Seed a multi-day diary and evaluate memory.")
    parser.add_argument("--user-id", default="", help="Optional explicit user id; default creates an ephemeral one.")
    parser.add_argument("--timezone", default="Asia/Singapore")
    parser.add_argument("--days", type=int, default=12, help="Span for the diary timeline (days back from --now).")
    parser.add_argument("--now", default="", help="ISO timestamp for evaluation reference (default: current UTC).")
    parser.add_argument("--use-claude", action="store_true", help="Allow Claude synthesis for the stored brief.")
    parser.add_argument("--ingest-supermemory", action="store_true", help="Try to ingest timestamped episodes into Supermemory.")
    parser.add_argument("--ingest-graphiti", action="store_true", help="Try to ingest timestamped episodes into Graphiti.")
    parser.add_argument("--episodes", type=int, default=4, help="Max episodes to ingest into external memory.")
    parser.add_argument("--keep", action="store_true", help="Do not delete the seeded rows at the end.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    args = parser.parse_args()

    user_id = args.user_id.strip() or f"diary-{uuid.uuid4().hex[:10]}"
    now_utc = _parse_now(args.now or None)
    tz_name = args.timezone

    turns = _build_default_diary(args.days)

    report: dict[str, Any] = {
        "user_id": user_id,
        "timezone": tz_name,
        "now_utc": now_utc.isoformat(timespec="seconds"),
        "seed": {},
        "external_ingest": {},
        "evaluation": {},
    }

    try:
        await _seed_user(user_id, tz_name)
        instance_ids = await _ensure_instances(user_id)
        report["seed"]["instances"] = instance_ids
        report["seed"]["facts"] = await _write_user_facts(user_id)
        seeded_turns = await _seed_chat_messages(user_id, now_utc, tz_name, turns)
        report["seed"]["turns"] = seeded_turns
        report["seed"]["open_loops"] = await _seed_open_loops(user_id, now_utc, tz_name)
        report["seed"]["observations"] = await _seed_observations(user_id, now_utc, tz_name, instance_ids)
        report["seed"]["schedules"] = await _seed_schedules(user_id, now_utc, tz_name)

        report["external_ingest"] = await _ingest_external_episodes(
            user_id,
            seeded_turns,
            ingest_supermemory=args.ingest_supermemory,
            ingest_graphiti=args.ingest_graphiti,
            max_episodes=max(0, int(args.episodes)),
        )

        report["evaluation"] = await _evaluate(user_id, now_utc, tz_name, use_claude=args.use_claude)
    finally:
        if not args.keep:
            await _cleanup(user_id)

    out = args.out.strip()
    if not out:
        Path("scripts/_out").mkdir(parents=True, exist_ok=True)
        out = f"scripts/_out/diary_report_{user_id}.json"
    Path(out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    print(f"\nseeded diary user_id={user_id} tz={tz_name} now={now_utc.isoformat(timespec='seconds')}")
    print(f"wrote report: {Path(out).resolve()}")
    # Small console highlights so you don't have to open JSON immediately.
    brief = ((report.get("evaluation") or {}).get("stored_brief") or {}).get("rendered") or ""
    print("\n=== stored situation brief (rendered) ===\n")
    print(brief.strip()[:1800] + ("\n... <truncated>" if len(brief) > 1800 else ""))
    return 0


def main() -> int:
    # Avoid importing dotenv in library code; keep this harness explicit.
    if os.path.exists(".env"):
        try:
            from donna_runtime.env import load_dotenv

            load_dotenv()
        except Exception:
            pass
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
