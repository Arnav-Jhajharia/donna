from __future__ import annotations

"""Full-system memory stress harness for Donna.

This is intentionally a harness, not a unit test. It creates disposable users,
seeds a realistic timeline across Donna's memory stores, refreshes the Living
Profile situation brief, probes the memory tools directly, optionally runs real
Donna/Sonnet turns, and writes a scored artifact bundle.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=_json_default))


def _append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(data, sort_keys=True, default=_json_default) + "\n")


@dataclass(frozen=True)
class Persona:
    slug: str
    display_name: str
    timezone: str
    phone_suffix: str
    profession: str
    primary_language: str
    wake_time: str
    currency: str
    style_note: str
    people: dict[str, str]


PERSONAS: tuple[Persona, ...] = (
    Persona(
        slug="operator",
        display_name="Aayam Stress Operator",
        timezone="Asia/Singapore",
        phone_suffix="sg",
        profession="Synthetic Sciences",
        primary_language="en",
        wake_time="11:11",
        currency="SGD",
        style_note="fast messy whatsapp style, building Donna under pressure",
        people={
            "Sarah": "investor/operator friend, waiting on the offer thread",
            "Luca": "design collaborator, owes deck feedback",
            "Priya": "calendar-heavy advisor",
        },
    ),
    Persona(
        slug="student",
        display_name="Maya Stress Student",
        timezone="America/New_York",
        phone_suffix="ny",
        profession="graduate student",
        primary_language="en",
        wake_time="08:20",
        currency="USD",
        style_note="move, classes, deadlines, sleep, money",
        people={
            "Sarah": "roommate handling lease paperwork",
            "Luca": "lab partner on the methods assignment",
            "Priya": "TA for systems class",
        },
    ),
    Persona(
        slug="relationship-heavy",
        display_name="Iris Stress Relations",
        timezone="Europe/London",
        phone_suffix="uk",
        profession="founder",
        primary_language="en",
        wake_time="09:00",
        currency="GBP",
        style_note="people, commitments, emotional continuity",
        people={
            "Sarah": "close friend, currently sensitive after a missed reply",
            "Luca": "potential hire, waiting for comp clarity",
            "Priya": "mentor who prefers concise updates",
        },
    ),
)


@dataclass
class SeededUser:
    persona: Persona
    user_id: str
    phone: str
    now_utc: datetime
    truth: dict[str, Any] = field(default_factory=dict)


@dataclass
class Check:
    category: str
    name: str
    passed: bool
    severity: str = "normal"
    evidence: Any = None


def _local_at(now_utc: datetime, tz_name: str, days_offset: int, hh: int, mm: int) -> datetime:
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    local_date = local_now.date() + timedelta(days=days_offset)
    return datetime.combine(local_date, time(hh, mm), tzinfo=tz)


def _week_local_at(now_utc: datetime, tz_name: str, week_offset: int, weekday: int, hh: int, mm: int) -> datetime:
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    monday = local_now.date() - timedelta(days=local_now.weekday()) + timedelta(weeks=week_offset)
    return datetime.combine(monday + timedelta(days=weekday), time(hh, mm), tzinfo=tz)


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _sum_expenses(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        fields = row.get("fields") or {}
        amount = fields.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        currency = str(fields.get("currency") or "UNKNOWN").upper()
        totals[currency] = _round_money(totals.get(currency, 0.0) + float(amount))
    return totals


def _tool_payload(result: dict[str, Any]) -> Any:
    return result.get("payload") if isinstance(result, dict) else None


def _contains_total(text: str, amount: float, currency: str) -> bool:
    low = text.lower()
    return f"{amount:g} {currency.lower()}" in low or f"{amount:.2f} {currency.lower()}" in low


async def _create_user(persona: Persona, user_id: str, phone: str) -> None:
    from sqlalchemy import text

    from backend.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, phone, name, profession, timezone, wake_time, facts, living_profile, "
                "onboarding_complete, onboarding_goals, has_google, is_sandbox, created_at, last_active_at) "
                "VALUES "
                "(:id, :phone, :name, :profession, :tz, :wake, '{}'::jsonb, '{}'::jsonb, "
                "true, '{}'::jsonb, true, true, :created_at, :last_active_at)"
            ),
            {
                "id": user_id,
                "phone": phone,
                "name": persona.display_name,
                "profession": persona.profession,
                "tz": persona.timezone,
                "wake": persona.wake_time,
                "created_at": datetime.now(UTC).replace(tzinfo=None),
                "last_active_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        await session.commit()


async def _ensure_instances(user_id: str) -> dict[str, str]:
    from backend.db.models import DonnaInstance
    from backend.db.session import async_session

    kinds = ("expense", "sleep", "mood", "meal", "exercise", "academic", "relationship")
    async with async_session() as session:
        instances: dict[str, str] = {}
        for kind in kinds:
            row = DonnaInstance(
                id=str(uuid.uuid4()),
                user_id=user_id,
                primitive="track",
                connector="whatsapp_manual",
                label=kind,
                config={"type": kind, "source": "memory_stress"},
                spec={"source": "memory_stress", "observation_type": kind},
                status="active",
            )
            session.add(row)
            instances[kind] = row.id
        await session.commit()
    return instances


async def _write_user_facts(seeded: SeededUser) -> dict[str, str]:
    from backend.memory.user_facts.api import update_user_fact
    from backend.memory.user_facts.schema import Confidence, FactKey, Source

    p = seeded.persona
    facts = {
        FactKey.PREFERRED_NAME.value: p.display_name.split()[0],
        FactKey.CURRENT_TIMEZONE.value: p.timezone,
        FactKey.PRIMARY_LANGUAGE.value: p.primary_language,
        FactKey.PROFESSION.value: p.profession,
        FactKey.WAKE_TIME.value: p.wake_time,
    }
    for key, value in facts.items():
        await update_user_fact(
            user_id=seeded.user_id,
            key=key,
            value=value,
            source=Source.CONVERSATION_EXTRACTED,
            confidence=Confidence.HIGH,
        )
    return facts


async def _seed_postgres_memory(seeded: SeededUser, days: int) -> None:
    from backend.db.models import CalendarEntry, ChatMessage, DonnaSchedule, Document, Fact, Observation, OpenLoop
    from backend.db.session import async_session

    p = seeded.persona
    instances = await _ensure_instances(seeded.user_id)
    now = seeded.now_utc
    currency = p.currency

    today_recent = _aware_utc(now - timedelta(hours=1))
    one_hour_ago = today_recent
    today_midnight_edge = _local_at(now, p.timezone, 0, 0, 30)
    yesterday_edge = _local_at(now, p.timezone, -1, 23, 30)
    yesterday_evening = _local_at(now, p.timezone, -1, 20, 15)
    this_week_mid = _week_local_at(now, p.timezone, 0, min(2, max(0, now.astimezone(ZoneInfo(p.timezone)).weekday())), 13, 5)
    last_week_a = _week_local_at(now, p.timezone, -1, 1, 14, 0)
    last_week_b = _week_local_at(now, p.timezone, -1, 4, 19, 45)
    next_week_a = _week_local_at(now, p.timezone, 1, 1, 10, 0)
    next_week_b = _week_local_at(now, p.timezone, 1, 3, 16, 30)

    chat_rows = [
        (last_week_a, "user", f"sarah said the offer is interesting but she needs numbers. {p.style_note}"),
        (last_week_a + timedelta(minutes=3), "assistant", "numbers first. vibes after."),
        (last_week_b, "user", "luca can review the deck if i send it by friday"),
        (last_week_b + timedelta(minutes=2), "assistant", "good. that becomes a thread."),
        (yesterday_evening, "user", "i slept 6.5 hours yesterday and woke up fried"),
        (yesterday_evening + timedelta(minutes=1), "assistant", "noted. fried is data, sadly."),
        (one_hour_ago, "user", "coffee was painful today"),
        (one_hour_ago + timedelta(minutes=1), "assistant", "coffee pricing remains hostile."),
        (now - timedelta(minutes=25), "user", "priya wants the crisp version before the meeting"),
    ]

    expenses = [
        {
            "label": "today coffee",
            "at": today_recent,
            "amount": 6.0,
            "item": "coffee",
            "merchant": "grab office cafe",
        },
        {
            "label": "today cab",
            "at": today_midnight_edge,
            "amount": 18.0,
            "item": "cab",
            "merchant": "grab",
        },
        {
            "label": "yesterday dinner",
            "at": yesterday_edge,
            "amount": 22.0,
            "item": "dinner",
            "merchant": "canteen",
        },
        {
            "label": "this week supplies",
            "at": this_week_mid,
            "amount": 13.0,
            "item": "supplies",
            "merchant": "campus shop",
        },
        {
            "label": "last week supplies",
            "at": last_week_a,
            "amount": 40.0,
            "item": "supplies",
            "merchant": "muji",
        },
        {
            "label": "last week dinner",
            "at": last_week_b,
            "amount": 31.0,
            "item": "dinner",
            "merchant": "team dinner",
        },
    ]

    observations = [
        *[
            {
                "type": "expense",
                "instance_id": instances["expense"],
                "event_time": row["at"],
                "tags": {"item": row["item"], "merchant": row["merchant"], "source": "memory_stress"},
                "fields": {"amount": row["amount"], "currency": currency, "item": row["item"], "merchant": row["merchant"]},
                "raw": f"spent {row['amount']:g} {currency} on {row['item']}",
            }
            for row in expenses
        ],
        {
            "type": "sleep",
            "instance_id": instances["sleep"],
            "event_time": yesterday_evening,
            "tags": {"source": "memory_stress"},
            "fields": {"hours": 6.5, "quality": "fried"},
            "raw": "slept 6.5 hours and woke up fried",
        },
        {
            "type": "mood",
            "instance_id": instances["mood"],
            "event_time": one_hour_ago,
            "tags": {"source": "memory_stress"},
            "fields": {"score": 4, "label": "stressed"},
            "raw": "stressed but still moving",
        },
        {
            "type": "meal",
            "instance_id": instances["meal"],
            "event_time": now - timedelta(hours=4),
            "tags": {"meal_type": "lunch", "source": "memory_stress"},
            "fields": {"item": "rice bowl", "protein_g": 28},
            "raw": "rice bowl for lunch",
        },
        {
            "type": "exercise",
            "instance_id": instances["exercise"],
            "event_time": now - timedelta(days=2),
            "tags": {"source": "memory_stress"},
            "fields": {"minutes": 35, "kind": "walk"},
            "raw": "35 min walk",
        },
    ]

    active_loops = [
        {
            "content": "finish Donna full memory stress harness",
            "created_at": now - timedelta(hours=3),
            "source_message": "finish building donna",
        },
        {
            "content": "reply to Sarah about the offer numbers",
            "created_at": now - timedelta(days=2),
            "source_message": "sarah needs numbers",
        },
        {
            "content": "send Priya the crisp version before the meeting",
            "created_at": now - timedelta(minutes=25),
            "source_message": "priya wants the crisp version",
        },
    ]
    closed_loops = [
        {
            "content": "send Luca the deck for Friday review",
            "created_at": last_week_b,
            "resolved_at": yesterday_evening,
            "source_message": "luca can review the deck",
        }
    ]

    calendars = [
        {
            "title": "Priya review meeting",
            "start_time": now + timedelta(hours=2),
            "end_time": now + timedelta(hours=3),
            "location": "Zoom",
            "category": "meeting",
        },
        {
            "title": "Sarah offer numbers call",
            "start_time": next_week_a,
            "end_time": next_week_a + timedelta(minutes=45),
            "location": "Google Meet",
            "category": "people",
        },
    ]
    schedules = [
        {
            "fire_at": now + timedelta(hours=1),
            "origin": "donna",
            "context": {"message": "nudge before Priya meeting", "source": "memory_stress"},
        },
        {
            "fire_at": next_week_b,
            "origin": "user",
            "context": {"message": "remind me to follow up with Luca", "source": "memory_stress"},
        },
    ]

    fact_rows = [
        Fact(
            id=str(uuid.uuid4()),
            user_id=seeded.user_id,
            subject=name.lower(),
            predicate="relationship_context",
            object=desc,
            object_json={"name": name, "description": desc, "source": "memory_stress"},
            confidence=0.95,
            source="memory_stress",
            t_valid_from=_utc_naive(last_week_a),
            t_recorded_from=_utc_naive(last_week_a),
            created_at=_utc_naive(last_week_a),
        )
        for name, desc in p.people.items()
    ]

    document = Document(
        id=str(uuid.uuid4()),
        user_id=seeded.user_id,
        storage_path=f"memory_stress/{seeded.user_id}/offer_notes.txt",
        extracted_text="Sarah offer notes: needs numbers, timeline, and downside clarity.",
        filename="offer_notes.txt",
        mime_type="text/plain",
        file_size_bytes=72,
        source="memory_stress",
        processing_status="ready",
        created_at=_utc_naive(last_week_a),
    )

    async with async_session() as session:
        for at, role, content in chat_rows:
            session.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    role=role,
                    content=content,
                    wa_message_id=f"stress_{seeded.user_id}_{uuid.uuid4().hex[:10]}",
                    created_at=_utc_naive(at),
                )
            )
        for row in observations:
            session.add(
                Observation(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    instance_id=row["instance_id"],
                    type=row["type"],
                    event_time=_utc_naive(row["event_time"]),
                    tags=row["tags"],
                    fields=row["fields"],
                    raw=row["raw"],
                    confidence=1.0,
                    source="memory_stress",
                    lineage=["memory_stress_seed"],
                    created_at=_utc_naive(row["event_time"]),
                )
            )
        for row in active_loops:
            session.add(
                OpenLoop(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    content=row["content"],
                    source_message=row["source_message"],
                    status="active",
                    created_at=_utc_naive(row["created_at"]),
                )
            )
        for row in closed_loops:
            session.add(
                OpenLoop(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    content=row["content"],
                    source_message=row["source_message"],
                    status="closed",
                    created_at=_utc_naive(row["created_at"]),
                    resolved_at=_utc_naive(row["resolved_at"]),
                )
            )
        for row in calendars:
            session.add(
                CalendarEntry(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    title=row["title"],
                    start_time=_utc_naive(row["start_time"]),
                    end_time=_utc_naive(row["end_time"]),
                    location=row["location"],
                    category=row["category"],
                    google_event_id=f"stress_{uuid.uuid4().hex[:10]}",
                    created_at=_utc_naive(now),
                )
            )
        for row in schedules:
            session.add(
                DonnaSchedule(
                    id=str(uuid.uuid4()),
                    user_id=seeded.user_id,
                    phone=seeded.phone,
                    fire_at=_utc_naive(row["fire_at"]),
                    origin=row["origin"],
                    context=row["context"],
                    fired=False,
                    status="pending",
                    created_at=_utc_naive(now),
                )
            )
        session.add_all(fact_rows)
        session.add(document)
        await session.commit()

    today_total = 24.0
    yesterday_total = 22.0
    this_week_total = today_total + yesterday_total + 13.0
    last_week_total = 71.0
    seeded.truth.update(
        {
            "user_id": seeded.user_id,
            "persona": p.slug,
            "timezone": p.timezone,
            "currency": currency,
            "facts": {
                "people": p.people,
                "style_note": p.style_note,
            },
            "expected_expense_totals": {
                "today": {currency: today_total},
                "yesterday": {currency: yesterday_total},
                "this_week": {currency: this_week_total},
                "last_week": {currency: last_week_total},
            },
            "expected_sleep": {"yesterday_hours": 6.5},
            "active_open_loops": [row["content"] for row in active_loops],
            "closed_open_loops": [row["content"] for row in closed_loops],
            "calendar_titles": [row["title"] for row in calendars],
            "schedule_messages": [row["context"]["message"] for row in schedules],
            "anchors": {
                "today": now.isoformat(),
                "one_hour_ago": one_hour_ago.isoformat(),
                "yesterday": yesterday_evening.isoformat(),
                "this_week": this_week_mid.isoformat(),
                "last_week": last_week_a.isoformat(),
                "next_week": next_week_a.isoformat(),
            },
            "notes": {
                "vague_feeling_not_structured": "coffee was painful today is in chat, but structured expense comes from explicit seeded observation.",
                "context_only_not_rewritten": "wrong-user and prompt-context rewrites are checked by prompt scans and fact counts.",
            },
        }
    )


async def _ingest_live_providers(seeded: SeededUser, max_episodes: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "supermemory": {"attempted": 0, "ok": 0, "available": False},
        "graphiti": {"attempted": 0, "ok": 0, "available": False},
        "documents": {"attempted": 0, "ok": 0, "note": "document chunk ingestion is not exposed by the local wrapper"},
    }
    episodes = [
        f"{seeded.persona.display_name}: Sarah needs numbers before deciding on the offer. Donna should connect this to offer follow-up.",
        f"{seeded.persona.display_name}: Luca said he can review the deck if it arrives by Friday. Later the loop was closed.",
        f"{seeded.persona.display_name}: Priya wants the crisp version before today's meeting.",
        f"{seeded.persona.display_name}: coffee spend and sleep are being tracked this week.",
    ][:max_episodes]

    from backend.memory.clients.supermemory import get_memory_client

    sm = get_memory_client()
    report["supermemory"]["available"] = sm.available
    if sm.available:
        for body in episodes:
            report["supermemory"]["attempted"] += 1
            episode_id = await sm.add_episode(
                user_id=seeded.user_id,
                content=body,
                metadata={"source": "memory_stress", "persona": seeded.persona.slug},
            )
            if episode_id:
                report["supermemory"]["ok"] += 1

    from backend.memory.clients import graphiti as graphiti_client

    for body in episodes:
        report["graphiti"]["attempted"] += 1
        ok = await graphiti_client.ingest_episode(
            user_id=seeded.user_id,
            content=body,
            reference_time=seeded.now_utc,
            metadata={"source": "memory_stress", "persona": seeded.persona.slug},
        )
        if ok:
            report["graphiti"]["ok"] += 1
    report["graphiti"]["available"] = report["graphiti"]["ok"] > 0
    return report


async def _refresh_and_read_memory(
    seeded: SeededUser,
    *,
    use_claude: bool,
    disable_llm_expansion: bool,
) -> dict[str, Any]:
    from backend.memory.synthesis.temporal_brief import BriefImplementation, collect_temporal_evidence, synthesize_and_store_temporal_brief
    from backend.memory.tools.list_calendar import list_calendar
    from backend.memory.tools.list_observations import list_observations
    from backend.memory.tools.list_open_loops import list_open_loops
    from backend.memory.tools.read_situation_brief import read_situation_brief
    from backend.memory.tools.recall_chat_thread import recall_chat_thread
    from backend.memory.tools.recall_document_chunks import recall_document_chunks
    from backend.memory.tools.recall_episodic import recall_episodic
    from backend.memory.tools.recall_graph import recall_graph
    from backend.memory.tools.smart_recall import smart_recall
    from backend.memory.user_facts.api import get_user_facts
    from backend.memory.user_facts.rendering import load_and_render
    from donna_runtime.context_builder import render_turn_context
    from donna_runtime.prompt import wrap_user_message_with_context

    brief = await synthesize_and_store_temporal_brief(
        seeded.user_id,
        implementation=BriefImplementation.WINDOWED_TIMELINE,
        now=seeded.now_utc,
        use_claude=use_claude,
    )
    evidence = await collect_temporal_evidence(seeded.user_id, now=seeded.now_utc)

    restore_call_structured = None
    if disable_llm_expansion:
        from backend.memory.retrieval import expansion as expansion_mod

        restore_call_structured = expansion_mod.call_structured

        async def _skip_structured_call(**_: Any) -> None:
            return None

        expansion_mod.call_structured = _skip_structured_call

    try:
        reads = {
            "user_facts": await get_user_facts(seeded.user_id),
            "observations": {
                "expense_today": await list_observations(seeded.user_id, type="expense", period="today", limit=20),
                "expense_yesterday": await list_observations(seeded.user_id, type="expense", period="yesterday", limit=20),
                "expense_this_week": await list_observations(seeded.user_id, type="expense", period="this_week", limit=50),
                "expense_last_week": await list_observations(seeded.user_id, type="expense", period="last_week", limit=50),
                "sleep_yesterday": await list_observations(seeded.user_id, type="sleep", period="yesterday", limit=20),
                "mood_today": await list_observations(seeded.user_id, type="mood", period="today", limit=20),
                "meal_today": await list_observations(seeded.user_id, type="meal", period="today", limit=20),
                "exercise_this_week": await list_observations(seeded.user_id, type="exercise", period="this_week", limit=20),
            },
            "open_loops": {
                "active": await list_open_loops(seeded.user_id, status="active", limit=20),
                "closed": await list_open_loops(seeded.user_id, status="closed", limit=20),
                "all": await list_open_loops(seeded.user_id, status="all", limit=30),
            },
            "calendar": await list_calendar(seeded.user_id, within_days=14, limit=20),
            "chat": await recall_chat_thread(seeded.user_id, limit=30),
            "situation_brief": await read_situation_brief(seeded.user_id),
            "smart_recall": {
                "spend_today": await smart_recall(seeded.user_id, "how much did i spend today", top_k=8),
                "spend_this_week": await smart_recall(seeded.user_id, "how much did i spend this week", top_k=8),
                "sleep_yesterday": await smart_recall(seeded.user_id, "how much sleep did i get yesterday", top_k=8),
                "forgetting": await smart_recall(seeded.user_id, "what am i forgetting", top_k=8),
                "today": await smart_recall(seeded.user_id, "what's going on today", top_k=8),
                "sarah": await smart_recall(seeded.user_id, "what's sarah's deal", top_k=8),
            },
            "providers": {
                "episodic": await recall_episodic(seeded.user_id, "sarah offer luca deck priya crisp", limit=8),
                "graph": await recall_graph(seeded.user_id, "Sarah Luca Priya offer deck relationship", limit=8),
                "documents": await recall_document_chunks(seeded.user_id, "offer numbers timeline downside", limit=5),
            },
        }
    finally:
        if restore_call_structured is not None:
            from backend.memory.retrieval import expansion as expansion_mod

            expansion_mod.call_structured = restore_call_structured

    user_model_block = await load_and_render(seeded.user_id)
    runtime_context = await render_turn_context(
        {
            "user_id": seeded.user_id,
            "_user_name": seeded.persona.display_name,
            "_user_timezone": seeded.persona.timezone,
            "_is_first_message": False,
            "_resume_session_id": "memory-stress-no-resume",
        }
    )
    wrapped = wrap_user_message_with_context("what's going on today", runtime_context, user_model_block)

    return {
        "brief": brief.model_dump(),
        "brief_rendered": brief.render(),
        "evidence_counts": {
            "chat": len(evidence.chat_messages),
            "facts": len(evidence.facts),
            "calendar": len(evidence.calendar),
            "schedules": len(evidence.schedules),
            "open_loops": len(evidence.open_loops),
            "observations": len(evidence.observations),
        },
        "reads": reads,
        "prompt_views": {
            "user_model_block": user_model_block,
            "runtime_context": runtime_context,
            "wrapped_user_prompt": wrapped,
        },
    }


def _score_backend(seeded: SeededUser, memory: dict[str, Any], all_seeded: list[SeededUser]) -> list[Check]:
    checks: list[Check] = []
    truth = seeded.truth
    currency = truth["currency"]
    reads = memory["reads"]

    for period, expected_by_currency in truth["expected_expense_totals"].items():
        result = reads["observations"][f"expense_{period}"]
        payload = _tool_payload(result)
        actual = _sum_expenses(payload if isinstance(payload, list) else [])
        checks.append(
            Check(
                "retrieval_quantitative",
                f"{seeded.persona.slug}: exact expense total {period}",
                actual == expected_by_currency,
                "critical",
                {"expected": expected_by_currency, "actual": actual, "status": result.get("status")},
            )
        )

    sleep_payload = _tool_payload(reads["observations"]["sleep_yesterday"])
    hours = None
    if isinstance(sleep_payload, list) and sleep_payload:
        hours = (sleep_payload[0].get("fields") or {}).get("hours")
    checks.append(
        Check(
            "retrieval_quantitative",
            f"{seeded.persona.slug}: exact sleep yesterday",
            hours == truth["expected_sleep"]["yesterday_hours"],
            "critical",
            {"expected": truth["expected_sleep"]["yesterday_hours"], "actual": hours},
        )
    )

    for key, period in (("spend_today", "today"), ("spend_this_week", "this_week")):
        result = reads["smart_recall"][key]
        payload = _tool_payload(result)
        first = payload[0] if isinstance(payload, list) and payload else {}
        expected = truth["expected_expense_totals"][period][currency]
        content = str(first.get("content") or "")
        checks.append(
            Check(
                "retrieval_auto_routing",
                f"{seeded.persona.slug}: smart_recall {period} observations first",
                first.get("source") == "observations" and _contains_total(content, expected, currency),
                "critical",
                {"first": first, "expected_total": expected, "currency": currency, "status": result.get("status")},
            )
        )

    active_payload = _tool_payload(reads["open_loops"]["active"])
    active_text = "\n".join(row.get("content", "") for row in active_payload if isinstance(row, dict)) if isinstance(active_payload, list) else ""
    closed_payload = _tool_payload(reads["open_loops"]["closed"])
    closed_text = "\n".join(row.get("content", "") for row in closed_payload if isinstance(row, dict)) if isinstance(closed_payload, list) else ""
    for loop in truth["active_open_loops"]:
        checks.append(
            Check(
                "open_loop_lifecycle",
                f"{seeded.persona.slug}: active loop found: {loop[:32]}",
                loop in active_text,
                "critical",
                {"active_text": active_text},
            )
        )
    for loop in truth["closed_open_loops"]:
        checks.append(
            Check(
                "open_loop_lifecycle",
                f"{seeded.persona.slug}: closed loop excluded from active: {loop[:32]}",
                loop not in active_text and loop in closed_text,
                "critical",
                {"active_text": active_text, "closed_text": closed_text},
            )
        )

    situation = _tool_payload(reads["situation_brief"])
    required_keys = {
        "current_status",
        "last_week",
        "this_week",
        "next_week",
        "open_loops",
        "evidence_used",
        "generated_at",
    }
    checks.append(
        Check(
            "situation_brief",
            f"{seeded.persona.slug}: situation brief required keys",
            isinstance(situation, dict) and required_keys.issubset(situation.keys()),
            "critical",
            {"keys": sorted(situation.keys()) if isinstance(situation, dict) else None},
        )
    )
    evidence = situation.get("evidence_used", {}) if isinstance(situation, dict) else {}
    for key in ("chat", "observations", "open_loops", "schedules"):
        checks.append(
            Check(
                "situation_brief",
                f"{seeded.persona.slug}: brief evidence nonzero {key}",
                int(evidence.get(key) or 0) > 0,
                "critical",
                {"evidence_used": evidence},
            )
        )
    generated_at = str(situation.get("generated_at") or "") if isinstance(situation, dict) else ""
    expected_date = seeded.now_utc.date().isoformat()
    checks.append(
        Check(
            "situation_brief",
            f"{seeded.persona.slug}: brief freshness date",
            generated_at.startswith(expected_date),
            "critical",
            {"generated_at": generated_at, "expected_date": expected_date},
        )
    )

    prompt = memory["prompt_views"]["wrapped_user_prompt"]
    checks.append(
        Check(
            "prompt_context",
            f"{seeded.persona.slug}: wrapped prompt contains user model and situation brief",
            "## USER MODEL" in prompt and "SITUATION BRIEF" in prompt and seeded.persona.display_name.split()[0] in prompt,
            "critical",
            {"prompt_chars": len(prompt)},
        )
    )
    wrong_tokens: list[str] = []
    for other in all_seeded:
        if other.user_id == seeded.user_id:
            continue
        if other.user_id in prompt:
            wrong_tokens.append(other.user_id)
        other_name = other.persona.display_name.split()[0]
        if other_name in prompt:
            wrong_tokens.append(other_name)
    checks.append(
        Check(
            "wrong_user_leakage",
            f"{seeded.persona.slug}: no wrong-user memory in prompt",
            not wrong_tokens,
            "critical",
            {"wrong_tokens": wrong_tokens},
        )
    )

    calendar_payload = _tool_payload(reads["calendar"])
    calendar_text = "\n".join(row.get("title", "") for row in calendar_payload if isinstance(row, dict)) if isinstance(calendar_payload, list) else ""
    for title in truth["calendar_titles"]:
        checks.append(
            Check(
                "calendar_schedule",
                f"{seeded.persona.slug}: calendar event found {title}",
                title in calendar_text,
                "normal",
                {"calendar_text": calendar_text, "status": reads["calendar"].get("status")},
            )
        )

    providers = reads["providers"]
    for key in ("episodic", "graph", "documents"):
        result = providers[key]
        checks.append(
            Check(
                "provider_availability",
                f"{seeded.persona.slug}: {key} provider read does not crash",
                result.get("status") in {"ok", "no_hits", "degraded"},
                "warning",
                {"status": result.get("status"), "payload": result.get("payload")},
            )
        )

    return checks


def _score_model_turns(turns: list[dict[str, Any]]) -> list[Check]:
    checks: list[Check] = []
    if not turns:
        checks.append(Check("model_behavior", "real model turns skipped", True, "warning", {"turns": 0}))
        return checks
    terminal_ok = 0
    fallback_count = 0
    raw_dump_failures: list[str] = []
    mechanics_failures: list[str] = []
    for row in turns:
        trace = row.get("trace") or {}
        calls = trace.get("tool_calls") or []
        if calls and str(calls[-1].get("tool", "")).endswith("send_burst"):
            terminal_ok += 1
        if calls and (calls[-1].get("inputs") or {}).get("fallback"):
            fallback_count += 1
        reply = str(trace.get("result_text") or "")
        if re.search(r"\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}", reply):
            raw_dump_failures.append(row.get("message", ""))
        if re.search(r"\b(tool|memory tool|according to memory|based on what i found)\b", reply.lower()):
            mechanics_failures.append(row.get("message", ""))
    ratio = terminal_ok / len(turns)
    checks.append(
        Check(
            "model_behavior",
            "real model turns terminate with send_burst >=95%",
            ratio >= 0.95,
            "critical",
            {"terminal_ok": terminal_ok, "turns": len(turns), "ratio": ratio, "fallback_count": fallback_count},
        )
    )
    checks.append(
        Check(
            "model_behavior",
            "model replies do not dump timestamp rows",
            not raw_dump_failures,
            "normal",
            {"failures": raw_dump_failures},
        )
    )
    checks.append(
        Check(
            "model_behavior",
            "model replies do not expose tool mechanics",
            not mechanics_failures,
            "normal",
            {"failures": mechanics_failures},
        )
    )
    return checks


async def _run_model_turns(seeded_users: list[SeededUser], memories: dict[str, dict[str, Any]], args: argparse.Namespace, out_dir: Path) -> list[dict[str, Any]]:
    if args.model_turns <= 0:
        return []

    from donna_runtime.config import DonnaAgentConfig
    from donna_runtime.runner import donna_turn

    messages = (
        "how much did i spend today",
        "what am i forgetting",
        "what's going on today",
        "what changed since yesterday",
        "what should i focus on next",
    )
    rows: list[dict[str, Any]] = []
    trace_path = out_dir / "model_turns.jsonl"
    for seeded in seeded_users:
        memory = memories[seeded.user_id]
        for message in messages[: args.model_turns]:
            cfg = DonnaAgentConfig(
                user_id=seeded.user_id,
                tool_mode="real",
                max_turns=6,
                request_timeout_s=args.turn_timeout,
                system_context=memory["prompt_views"]["runtime_context"],
                user_model_block=memory["prompt_views"]["user_model_block"],
                chat_already_persisted=True,
                stateless_sessions=True,
                trace_file=trace_path,
            )
            trace = await donna_turn(message, cfg)
            row = {
                "user_id": seeded.user_id,
                "persona": seeded.persona.slug,
                "message": message,
                "trace": trace.to_dict(),
            }
            rows.append(row)
            _append_jsonl(trace_path, row)
    return rows


async def _cleanup(seeded_users: list[SeededUser]) -> None:
    from sqlalchemy import delete

    from backend.db.models import (
        CalendarEntry,
        ChatMessage,
        Document,
        DonnaInstance,
        DonnaSchedule,
        Fact,
        ImageToolEvent,
        InboundMessage,
        Observation,
        OpenLoop,
        ProceduralRule,
        RunTrace,
        User,
        UserSession,
    )
    from backend.db.session import async_session

    async with async_session() as session:
        for seeded in seeded_users:
            user_id = seeded.user_id
            for model in (
                ChatMessage,
                Observation,
                OpenLoop,
                CalendarEntry,
                DonnaSchedule,
                Document,
                ProceduralRule,
                RunTrace,
                Fact,
                DonnaInstance,
                ImageToolEvent,
            ):
                await session.execute(delete(model).where(model.user_id == user_id))
            await session.execute(delete(UserSession).where(UserSession.user_id == user_id))
            await session.execute(delete(InboundMessage).where(InboundMessage.phone == seeded.phone))
            await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


def _scorecard(checks: list[Check]) -> dict[str, Any]:
    by_category: dict[str, dict[str, Any]] = {}
    for check in checks:
        bucket = by_category.setdefault(check.category, {"passed": 0, "failed": 0, "checks": []})
        bucket["passed" if check.passed else "failed"] += 1
        bucket["checks"].append(
            {
                "name": check.name,
                "passed": check.passed,
                "severity": check.severity,
                "evidence": check.evidence,
            }
        )
    total = len(checks)
    passed = sum(1 for c in checks if c.passed)
    critical_failures = [c for c in checks if not c.passed and c.severity == "critical"]
    warning_failures = [c for c in checks if not c.passed and c.severity == "warning"]
    normal_failures = [c for c in checks if not c.passed and c.severity == "normal"]
    wrong_user_failures = [c for c in checks if not c.passed and c.category == "wrong_user_leakage"]
    score = round((passed / total) * 100, 2) if total else 100.0
    return {
        "overall_score": score,
        "passed": passed,
        "total": total,
        "critical_failures": [
            {"category": c.category, "name": c.name, "evidence": c.evidence} for c in critical_failures
        ],
        "normal_failures": [
            {"category": c.category, "name": c.name, "evidence": c.evidence} for c in normal_failures
        ],
        "warning_failures": [
            {"category": c.category, "name": c.name, "evidence": c.evidence} for c in warning_failures
        ],
        "wrong_user_leakage_failures": len(wrong_user_failures),
        "by_category": by_category,
        "acceptance": {
            "overall_at_least_90": score >= 90.0,
            "wrong_user_leakage_zero": len(wrong_user_failures) == 0,
            "no_critical_failures": len(critical_failures) == 0,
        },
    }


def _render_living_profile_md(memories: dict[str, dict[str, Any]], seeded_users: list[SeededUser]) -> str:
    lines = ["# Living Profile + Situation Brief", ""]
    for seeded in seeded_users:
        memory = memories[seeded.user_id]
        lines.extend(
            [
                f"## {seeded.persona.slug}",
                "",
                f"- user_id: `{seeded.user_id}`",
                f"- timezone: `{seeded.persona.timezone}`",
                "",
                "```text",
                memory["prompt_views"]["user_model_block"],
                "```",
                "",
                "### Raw Brief",
                "",
                "```text",
                memory["brief_rendered"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _render_report(scorecard: dict[str, Any], seeded_users: list[SeededUser], provider_reports: dict[str, Any], out_dir: Path) -> str:
    lines = [
        "# Donna Memory Stress Report",
        "",
        f"- overall score: {scorecard['overall_score']}%",
        f"- passed: {scorecard['passed']} / {scorecard['total']}",
        f"- critical failures: {len(scorecard['critical_failures'])}",
        f"- wrong-user leakage failures: {scorecard['wrong_user_leakage_failures']}",
        f"- artifacts: `{out_dir}`",
        "",
        "## Users",
        "",
    ]
    for seeded in seeded_users:
        lines.append(f"- {seeded.persona.slug}: `{seeded.user_id}` in `{seeded.persona.timezone}`")
    lines.extend(["", "## Provider Status", ""])
    for user_id, report in provider_reports.items():
        slug = next((s.persona.slug for s in seeded_users if s.user_id == user_id), user_id)
        lines.append(f"- {slug}: `{json.dumps(report, sort_keys=True)}`")
    lines.extend(["", "## Category Scores", ""])
    for category, bucket in sorted(scorecard["by_category"].items()):
        total = bucket["passed"] + bucket["failed"]
        lines.append(f"- {category}: {bucket['passed']} / {total}")
    if scorecard["critical_failures"]:
        lines.extend(["", "## Critical Failures", ""])
        for failure in scorecard["critical_failures"]:
            lines.append(f"- {failure['category']}: {failure['name']}")
    if scorecard["normal_failures"]:
        lines.extend(["", "## Normal Failures", ""])
        for failure in scorecard["normal_failures"][:20]:
            lines.append(f"- {failure['category']}: {failure['name']}")
    if scorecard["warning_failures"]:
        lines.extend(["", "## Warnings", ""])
        for failure in scorecard["warning_failures"][:20]:
            lines.append(f"- {failure['category']}: {failure['name']}")
    lines.extend(
        [
            "",
            "## Artifact Map",
            "",
            "- `seed_truth.json`: canonical seeded ledger",
            "- `backend_reads.json`: direct outputs from memory tools",
            "- `model_turns.jsonl`: Donna turn traces when model turns are enabled",
            "- `living_profile.md`: rendered Living Profile and stored Situation Brief",
            "- `provider_dumps/`: Supermemory, Graphiti, and document read outputs",
            "- `scorecard.json`: machine-readable pass/fail breakdown",
        ]
    )
    return "\n".join(lines) + "\n"


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Stress test Donna's complete memory architecture.")
    parser.add_argument("--users", type=int, default=3, help="Number of synthetic users to seed, max 3 in the built-in persona set.")
    parser.add_argument("--days", type=int, default=14, help="Seeded lookback span. Values below 7 still keep last-week-like probes compact.")
    parser.add_argument("--now", default="", help="UTC ISO anchor for brief generation. Default: current UTC.")
    parser.add_argument("--out", default="", help="Output directory. Default: scripts/_out/memory_stress_<timestamp>.")
    parser.add_argument("--live-providers", action="store_true", help="Try Supermemory and Graphiti writes/searches.")
    parser.add_argument("--no-live-providers", action="store_true", help="Force provider writes off.")
    parser.add_argument("--judge", action="store_true", help="Reserved for a future LLM judge pass. Currently recorded as skipped.")
    parser.add_argument("--model-turns", type=int, default=2, help="Real Donna turns per synthetic user. Use 0 for backend-only fast stress.")
    parser.add_argument("--episodes", type=int, default=4, help="Max live-provider episodes per user.")
    parser.add_argument("--turn-timeout", type=float, default=45.0, help="Timeout per real Donna turn.")
    parser.add_argument("--keep", action="store_true", help="Keep disposable users in Postgres after the run.")
    args = parser.parse_args()

    _load_dotenv()
    now_utc = _parse_now(args.now)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "scripts" / "_out" / f"memory_stress_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "provider_dumps").mkdir(exist_ok=True)

    requested_users = max(1, min(args.users, len(PERSONAS)))
    personas = list(PERSONAS[:requested_users])
    seeded_users = [
        SeededUser(
            persona=p,
            user_id=f"memstress-{p.slug}-{uuid.uuid4().hex[:10]}",
            phone=f"+1555000{idx:02d}{p.phone_suffix}",
            now_utc=now_utc,
        )
        for idx, p in enumerate(personas, start=1)
    ]

    provider_reports: dict[str, Any] = {}
    memories: dict[str, dict[str, Any]] = {}
    checks: list[Check] = []
    model_rows: list[dict[str, Any]] = []
    live_providers = bool(args.live_providers and not args.no_live_providers)

    try:
        for seeded in seeded_users:
            await _create_user(seeded.persona, seeded.user_id, seeded.phone)
            facts = await _write_user_facts(seeded)
            await _seed_postgres_memory(seeded, args.days)
            seeded.truth["user_facts"] = facts
            if live_providers:
                provider_reports[seeded.user_id] = await _ingest_live_providers(seeded, args.episodes)
            else:
                provider_reports[seeded.user_id] = {
                    "supermemory": {"skipped": True},
                    "graphiti": {"skipped": True},
                    "documents": {"skipped": True},
                }

        for seeded in seeded_users:
            memories[seeded.user_id] = await _refresh_and_read_memory(
                seeded,
                use_claude=bool(args.judge and live_providers),
                disable_llm_expansion=not live_providers,
            )
            checks.extend(_score_backend(seeded, memories[seeded.user_id], seeded_users))

        if args.judge:
            checks.append(
                Check(
                    "judge",
                    "LLM judge pass currently recorded as skipped unless implemented separately",
                    True,
                    "warning",
                    {"judge_requested": True},
                )
            )

        model_rows = await _run_model_turns(seeded_users, memories, args, out_dir)
        checks.extend(_score_model_turns(model_rows))

        seed_truth = {
            "run": {
                "now_utc": now_utc.isoformat(),
                "users": len(seeded_users),
                "days": args.days,
                "live_providers": live_providers,
                "model_turns_per_user": args.model_turns,
            },
            "users": {seeded.user_id: seeded.truth for seeded in seeded_users},
        }
        backend_reads = {
            seeded.user_id: {
                "persona": seeded.persona.slug,
                "memory": memories[seeded.user_id],
            }
            for seeded in seeded_users
        }
        provider_dumps = {
            seeded.user_id: {
                "persona": seeded.persona.slug,
                "provider_report": provider_reports.get(seeded.user_id),
                "provider_reads": memories[seeded.user_id]["reads"]["providers"],
            }
            for seeded in seeded_users
        }
        scorecard = _scorecard(checks)

        _write_json(out_dir / "seed_truth.json", seed_truth)
        _write_json(out_dir / "backend_reads.json", backend_reads)
        for user_id, dump in provider_dumps.items():
            _write_json(out_dir / "provider_dumps" / f"{user_id}.json", dump)
        (out_dir / "living_profile.md").write_text(_render_living_profile_md(memories, seeded_users))
        _write_json(out_dir / "scorecard.json", scorecard)
        (out_dir / "memory_stress_report.md").write_text(
            _render_report(scorecard, seeded_users, provider_reports, out_dir)
        )
        if not (out_dir / "model_turns.jsonl").exists():
            (out_dir / "model_turns.jsonl").write_text("")

        print(f"memory stress artifacts: {out_dir}")
        print(f"overall score: {scorecard['overall_score']}% ({scorecard['passed']}/{scorecard['total']})")
        if scorecard["critical_failures"]:
            print(f"critical failures: {len(scorecard['critical_failures'])}")
            for failure in scorecard["critical_failures"][:10]:
                print(f"- {failure['category']}: {failure['name']}")
        return 0 if scorecard["acceptance"]["overall_at_least_90"] and scorecard["acceptance"]["wrong_user_leakage_zero"] else 1
    finally:
        if not args.keep:
            await _cleanup(seeded_users)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
