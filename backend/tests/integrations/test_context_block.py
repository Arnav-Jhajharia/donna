from __future__ import annotations

import pytest

from backend.integrations import state
from donna_runtime.context_builder import render_turn_context


@pytest.mark.asyncio
async def test_turn_context_includes_integrations_block(db) -> None:
    await state.upsert_pending("u1", "google", "calendar")
    await state.mark_connected("u1", "google", "calendar", connection_id="c1")

    ctx = await render_turn_context({"user_id": "u1"})
    assert "[INTEGRATIONS]" in ctx
    assert "google_calendar: connected" in ctx


@pytest.mark.asyncio
async def test_turn_context_omits_block_when_empty(db) -> None:
    ctx = await render_turn_context({"user_id": "u_no_integrations"})
    assert "[INTEGRATIONS]" not in ctx
