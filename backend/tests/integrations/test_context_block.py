from __future__ import annotations

import pytest

from backend.integrations import state
from donna_runtime import context_builder
from donna_runtime.context_builder import render_turn_context


@pytest.fixture(autouse=True)
def stub_reconcile(monkeypatch):
    """Stop the per-turn reconcile from hitting the live Composio API in
    tests — the env may have a real key, and the test fixture only
    monkeypatches the DB. Prevents flips from real Composio truth
    polluting the local-only assertions."""
    async def _noop(user_id, toolkits=None):
        return {}
    monkeypatch.setattr(
        "backend.memory.tools.check_integration_status.reconcile_with_composio",
        _noop,
    )
    context_builder._LAST_INTEGRATIONS_RECONCILE.clear()


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
