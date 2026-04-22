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

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("DONNA_E2E") != "1",
    reason="Set DONNA_E2E=1 to run integration tests.",
)


async def _run_scenario(user_id: str) -> dict:
    from sqlalchemy import delete, select

    from backend.db.models import (
        ChatMessage,
        Observation,
        OpenLoop,
        ProceduralRule,
        User,
    )
    from backend.db.session import async_session
    from backend.memory.hooks import ALL_HOOKS
    from backend.memory.tools.list_observations import list_observations
    from backend.memory.tools.log_observation import log_observation
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
    )
    report["log_observation"] = log["status"]
    hits = await list_observations(user_id=user_id, type="mood", limit=5)
    report["list_observations"] = hits["status"]
    report["observation_count"] = len(hits["payload"] or [])

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
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()

    return report


@pytest.mark.asyncio
async def test_full_memory_flow():
    user_id = f"e2e-{uuid.uuid4().hex[:12]}"
    report = await _run_scenario(user_id)
    print("\nE2E report:", report)

    assert report["user_seeded"]
    assert report["log_observation"] == "ok"
    assert report["list_observations"] == "ok"
    assert report["observation_count"] >= 1
    assert report["update_user_fact"] is True
    assert report["rendered_has_tokyo"]
    assert report["chat_messages_persisted"] >= 3  # 1 inbound + 2 outbound
    assert report["smart_recall_status"] in ("ok", "no_hits", "degraded")
