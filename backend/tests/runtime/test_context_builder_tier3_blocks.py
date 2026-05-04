"""Real block builders for the Tier 3 input contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import (
    ChatMessage,
    PendingProactiveNote,
    ProactiveDispatchTelemetry,
    generate_uuid,
    utcnow,
)
from donna_runtime.context_builder_tier3 import (
    load_day_view_block,
    load_user_model_block_for_tier3,
    load_pending_notes_block,
)


@pytest.mark.asyncio
async def test_load_user_model_block_for_tier3_unknown_user_returns_placeholder(db):
    """Unknown user → degraded placeholder string, never raises."""
    block = await load_user_model_block_for_tier3(user_id="nonexistent_xyz")
    assert isinstance(block, str)
    assert len(block) > 0


@pytest.mark.asyncio
async def test_load_user_model_block_for_tier3_returns_string_for_known_user(db):
    """The conftest fixture seeds u1; should return a non-empty string."""
    block = await load_user_model_block_for_tier3(user_id="u1")
    assert isinstance(block, str)
    assert len(block) > 0


@pytest.mark.asyncio
async def test_load_pending_notes_block_no_notes_returns_placeholder(db):
    block = await load_pending_notes_block(user_id="u1")
    assert "no pending notes" in block.lower() or block.strip() == ""


@pytest.mark.asyncio
async def test_load_pending_notes_block_returns_active_notes(db):
    """Active rows in pending_proactive_notes should appear in the block."""
    now = utcnow()
    async with db() as session:
        note = PendingProactiveNote(
            id=generate_uuid(),
            user_id="u1",
            topic_key="thread_test",
            draft="hey, anthropic just shipped a new agent SDK feature",
            status="pending",
            source="email",
            created_at=now,
            expires_at=now + timedelta(hours=12),
        )
        session.add(note)
        await session.commit()

    block = await load_pending_notes_block(user_id="u1")
    assert "anthropic" in block
    assert "thread_test" in block


@pytest.mark.asyncio
async def test_load_day_view_block_no_activity_returns_compact_summary(db):
    block = await load_day_view_block(user_id="u1")
    assert isinstance(block, str)
    assert len(block) > 0
    # Empty day still has a header.
    assert "today" in block.lower() or "day" in block.lower()


@pytest.mark.asyncio
async def test_load_day_view_block_includes_proactive_fires(db):
    """Telemetry rows from today should appear in the block."""
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="u1",
            source="email",
            speech_act="heads_up",
            topic_key="thread_xyz",
            tier3_invoked=True,
            tier3_outcome="legacy_thin_directive",
            channel="whatsapp",
            counterfactual_legacy_outbound_count=1,
            counterfactual_fat_contract_outcome="input_built",
            event_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()

    block = await load_day_view_block(user_id="u1")
    assert "thread_xyz" in block or "heads_up" in block
    # The block should hint at fires_today count
    assert "fire" in block.lower() or "ping" in block.lower()
