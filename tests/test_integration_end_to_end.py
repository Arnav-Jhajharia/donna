"""End-to-end integration smoke test against live Supabase + Supermemory.

Not part of the default pytest run — gated behind DONNA_E2E=1 because it
requires network access, live API keys, and mutates real data.

Run with:
    DONNA_E2E=1 .venv/bin/python -m pytest tests/test_integration_end_to_end.py -v -s

Everything lives in one async test so all DB work happens on a single loop —
the module-level async engine in backend.db.session is pinned to the loop
of whichever coroutine first awaits it.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.getenv("DONNA_E2E") != "1",
        reason="Set DONNA_E2E=1 to run integration tests.",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def _run_scenario(user_id: str) -> dict:
    from sqlalchemy import delete, select

    from backend.db.models import (
        ChatMessage,
        DonnaInstance,
        Observation,
        OpenLoop,
        ProceduralRule,
        User,
    )
    from backend.db.session import async_session
    from backend.memory.hooks import ALL_HOOKS
    from backend.memory.tools.list_observations import list_observations
    from backend.memory.tools.log_observation import log_observation
    from backend.memory.tools.read_situation_brief import read_situation_brief
    from backend.memory.tools.refresh_situation_brief import refresh_situation_brief
    from backend.memory.tools.smart_recall import smart_recall
    from backend.memory.user_facts.api import update_user_fact
    from backend.memory.user_facts.rendering import load_and_render
    from backend.memory.user_facts.schema import Confidence, FactKey, Source

    report: dict = {}

    # 1. Seed user via raw SQL so existing NOT NULL columns (onboarding_*,
    # has_github, is_sandbox) get their table defaults.
    from sqlalchemy import text

    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, phone, name, timezone, facts, "
                "onboarding_complete, has_google, created_at) "
                "VALUES (:id, :phone, :name, :tz, '{}'::jsonb, false, false, now())"
            ),
            {"id": user_id, "phone": f"+e2e{user_id[-8:]}", "name": "E2E Tester", "tz": "Asia/Singapore"},
        )
        await session.commit()
    report["user_seeded"] = True

    # 2. log_observation → list_observations round-trip.
    log = await log_observation(
        user_id=user_id,
        type="mood",
        fields={"score": 7, "note": "moved to Tokyo"},
        tags={"source": "e2e"},
        event_time="2026-04-21T10:30:00+08:00",
    )
    report["log_observation"] = log["status"]
    report["log_refreshed_situation_brief"] = bool((log.get("payload") or {}).get("situation_brief_refreshed"))
    hits = await list_observations(user_id=user_id, type="mood", limit=5)
    report["list_observations"] = hits["status"]
    report["observation_count"] = len(hits["payload"] or [])
    report["observation_event_time"] = (
        hits["payload"][0].get("event_time") if hits["status"] == "ok" and hits["payload"] else None
    )

    refresh = await refresh_situation_brief(user_id=user_id)
    report["refresh_situation_brief"] = refresh["status"]
    situation = await read_situation_brief(user_id=user_id)
    report["read_situation_brief"] = situation["status"]
    report["situation_has_mood"] = "mood" in str(situation.get("payload", "")).lower()

    # 3. update_user_fact → rendering.
    ok = await update_user_fact(
        user_id=user_id,
        key=FactKey.HOME_CITY.value,
        value="Tokyo",
        source=Source.CONVERSATION_EXTRACTED,
        confidence=Confidence.HIGH,
    )
    report["update_user_fact"] = bool(ok)
    rendered = await load_and_render(user_id)
    report["rendered_has_tokyo"] = "Tokyo" in rendered

    # 4. Hooks: save_chat_messages + record_episode + ingest_to_graph.
    ctx = {
        "user_id": user_id,
        "inbound": "just moved to Tokyo for grad school, starting Monday",
        "outbound": ["noted — big move", "grad school in tokyo, congrats"],
        "tool_names": ["send_burst"],
        "terminator": "send_burst",
        "user_facts": {},
    }
    for hook in ALL_HOOKS:  # all four: save_chat, record_episode, ingest_graph, extract_facts
        await hook(ctx)

    async with async_session() as session:
        chat_rows = (
            await session.execute(select(ChatMessage).where(ChatMessage.user_id == user_id))
        ).scalars().all()
    report["chat_messages_persisted"] = len(chat_rows)

    # 5. smart_recall — Supermemory may take a moment to index.
    await asyncio.sleep(3)
    recall = await smart_recall(user_id=user_id, message="tokyo", top_k=5)
    report["smart_recall_status"] = recall["status"]

    # 5b. Verify extract_user_facts wrote home_city from the Haiku extractor.
    from backend.memory.user_facts.api import get_user_facts
    facts = await get_user_facts(user_id)
    report["extracted_home_city"] = facts.get("home_city", {}).get("value") if isinstance(facts.get("home_city"), dict) else None

    # 6. Cleanup.
    async with async_session() as session:
        for model in (ChatMessage, Observation, OpenLoop, ProceduralRule):
            await session.execute(delete(model).where(model.user_id == user_id))
        await session.execute(delete(DonnaInstance).where(DonnaInstance.user_id == user_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()

    return report


async def test_full_memory_flow():
    user_id = f"e2e-{uuid.uuid4().hex[:12]}"
    report = await _run_scenario(user_id)
    print("\nE2E report:", report)

    assert report["user_seeded"]
    assert report["log_observation"] == "ok"
    assert report["log_refreshed_situation_brief"] is True
    assert report["list_observations"] == "ok"
    assert report["observation_count"] >= 1
    assert report["observation_event_time"].startswith("2026-04-21T02:30:00")
    assert report["refresh_situation_brief"] == "ok"
    assert report["read_situation_brief"] == "ok"
    assert report["situation_has_mood"] is True
    assert report["update_user_fact"] is True
    assert report["rendered_has_tokyo"]
    assert report["chat_messages_persisted"] >= 3  # 1 inbound + 2 outbound
    assert report["smart_recall_status"] in ("ok", "no_hits", "degraded")


async def _run_period_boundary_scenario(base_id: str) -> dict:
    from sqlalchemy import delete, text

    from backend.db.models import DonnaInstance, Observation, User
    from backend.db.session import async_session
    from backend.memory.time import period_bounds
    from backend.memory.tools.list_observations import list_observations

    zones = {
        "singapore": "Asia/Singapore",
        "new_york": "America/New_York",
        "london": "Europe/London",
    }
    user_ids = {slug: f"{base_id}-{slug}" for slug in zones}
    report: dict = {}

    try:
        async with async_session() as session:
            for slug, tz_name in zones.items():
                user_id = user_ids[slug]
                await session.execute(
                    text(
                        "INSERT INTO users (id, phone, name, timezone, facts, "
                        "onboarding_complete, has_google, created_at) "
                        "VALUES (:id, :phone, :name, :tz, '{}'::jsonb, false, false, now())"
                    ),
                    {
                        "id": user_id,
                        "phone": f"+tz{uuid.uuid4().hex[:12]}",
                        "name": f"TZ Tester {slug}",
                        "tz": tz_name,
                    },
                )
                inst = DonnaInstance(
                    user_id=user_id,
                    primitive="track",
                    connector="whatsapp_manual",
                    label="boundary",
                    config={"type": "boundary"},
                    status="active",
                )
                session.add(inst)
                await session.flush()

                start, end = period_bounds("last_week", tz_name)
                assert start is not None and end is not None
                samples = {
                    "before": start - timedelta(seconds=1),
                    "inside": start + timedelta(hours=12),
                    "end_edge": end - timedelta(seconds=1),
                    "after": end,
                }
                for marker, event_time in samples.items():
                    session.add(
                        Observation(
                            user_id=user_id,
                            instance_id=inst.id,
                            type="boundary",
                            event_time=event_time,
                            fields={"marker": marker, "timezone": tz_name},
                            tags={"test": "period_boundary"},
                            confidence=1.0,
                        )
                    )
            await session.commit()

        for slug, tz_name in zones.items():
            res = await list_observations(
                user_id=user_ids[slug],
                type="boundary",
                period="last_week",
                limit=10,
            )
            payload = res.get("payload") or []
            markers = {row.get("fields", {}).get("marker") for row in payload}
            report[slug] = {
                "status": res["status"],
                "timezone": tz_name,
                "markers": sorted(markers),
                "local_times": [row.get("event_time_local") for row in payload],
            }
    finally:
        async with async_session() as session:
            for user_id in user_ids.values():
                await session.execute(delete(Observation).where(Observation.user_id == user_id))
                await session.execute(delete(DonnaInstance).where(DonnaInstance.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
            await session.commit()

    return report


async def test_observation_period_boundaries_respect_user_timezones():
    report = await _run_period_boundary_scenario(f"tz-e2e-{uuid.uuid4().hex[:8]}")
    print("\nPeriod boundary report:", report)

    assert set(report) == {"singapore", "new_york", "london"}
    for row in report.values():
        assert row["status"] == "ok"
        assert row["markers"] == ["end_edge", "inside"]
        assert all(row["timezone"] in str(local_time) for local_time in row["local_times"])
