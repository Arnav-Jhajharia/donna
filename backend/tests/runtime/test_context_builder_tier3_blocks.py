"""Real block builders for the Tier 3 input contract."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from db.models import PendingProactiveNote, generate_uuid, utcnow
from donna_runtime.context_builder_tier3 import (
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
