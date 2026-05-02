"""Tests for pending_intents.enqueue_intent + drain_for_toolkit.

The harness uses the in-memory aiosqlite ``db`` fixture from
``conftest.py`` so we exercise real model persistence paths. The
proactive turn-firing is monkey-patched out — we assert what was queued
to fire, not the brain output.
"""
from __future__ import annotations

import pytest

from backend.integrations import state
from backend.integrations.pending_intents import (
    drain_for_toolkit,
    enqueue_intent,
)


@pytest.fixture
def fake_brain(monkeypatch):
    """Capture proactive-turn fires instead of running the brain."""
    fired: list[dict] = []

    async def _fake_fire(user_id, intent, intent_id):
        fired.append({"user_id": user_id, "intent": intent, "intent_id": intent_id})

    monkeypatch.setattr(
        "backend.integrations.pending_intents._fire_proactive_turn",
        _fake_fire,
    )
    return fired


@pytest.mark.asyncio
async def test_enqueue_creates_pending_row(db) -> None:
    intent_id = await enqueue_intent(
        user_id="u1",
        toolkits=["gmail"],
        intent="summarize my gmail this week",
    )
    assert intent_id is not None

    from sqlalchemy import select
    from db.models import PendingIntegrationIntent

    async with db() as s:
        rows = (
            await s.execute(select(PendingIntegrationIntent))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "u1"
    assert rows[0].toolkits == ["gmail"]
    assert rows[0].intent == "summarize my gmail this week"
    assert rows[0].status == "pending"
    assert rows[0].expires_at is not None


@pytest.mark.asyncio
async def test_enqueue_dedupes_identical_pending_intent(db) -> None:
    """Re-enqueueing the same (toolkits, intent) for the same user should
    return the existing row id, not create a second one. Otherwise a
    flaky-tap retry would queue 5 copies."""
    first = await enqueue_intent(
        user_id="u1", toolkits=["gmail"], intent="summarize my gmail",
    )
    second = await enqueue_intent(
        user_id="u1", toolkits=["gmail"], intent="summarize my gmail",
    )
    assert first == second

    from sqlalchemy import select
    from db.models import PendingIntegrationIntent

    async with db() as s:
        rows = (
            await s.execute(select(PendingIntegrationIntent))
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_enqueue_normalises_toolkits(db) -> None:
    """Whitespace and order should not produce different rows."""
    first = await enqueue_intent(
        user_id="u1", toolkits=["gmail", "googlecalendar"], intent="x",
    )
    second = await enqueue_intent(
        user_id="u1", toolkits=[" googlecalendar ", "gmail "], intent="x",
    )
    assert first == second


@pytest.mark.asyncio
async def test_drain_fires_intent_when_toolkit_connected(db, fake_brain) -> None:
    """Once the toolkit lands, drain should fire the proactive turn and
    flip status to 'fired'."""
    await enqueue_intent(
        user_id="u1", toolkits=["gmail"], intent="summarize my gmail",
    )
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    fired = await drain_for_toolkit("u1", "gmail")

    assert fired == 1
    assert len(fake_brain) == 1
    assert fake_brain[0]["intent"] == "summarize my gmail"

    from sqlalchemy import select
    from db.models import PendingIntegrationIntent

    async with db() as s:
        row = (
            await s.execute(select(PendingIntegrationIntent))
        ).scalar_one()
    assert row.status == "fired"
    assert row.fired_at is not None


@pytest.mark.asyncio
async def test_drain_skips_when_required_toolkit_still_pending(db, fake_brain) -> None:
    """An intent needing gmail+slack should NOT fire when only gmail
    has connected — wait for slack too."""
    await enqueue_intent(
        user_id="u1", toolkits=["gmail", "slack"], intent="cross-post my email",
    )
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_g")

    fired = await drain_for_toolkit("u1", "gmail")

    assert fired == 0
    assert fake_brain == []

    # Now slack lands too — should fire on the second drain.
    await state.upsert_pending("u1", "composio", "slack")
    await state.mark_connected("u1", "composio", "slack", connection_id="ca_s")
    fired = await drain_for_toolkit("u1", "slack")
    assert fired == 1


@pytest.mark.asyncio
async def test_drain_marks_expired_intents(db, fake_brain) -> None:
    """Intents older than 24h should expire on drain, not fire."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from db.models import PendingIntegrationIntent

    intent_id = await enqueue_intent(
        user_id="u1", toolkits=["gmail"], intent="old ask",
    )
    # Force expiry into the past.
    async with db() as s:
        row = await s.get(PendingIntegrationIntent, intent_id)
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        await s.commit()

    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")
    fired = await drain_for_toolkit("u1", "gmail")

    assert fired == 0
    assert fake_brain == []

    async with db() as s:
        row = await s.get(PendingIntegrationIntent, intent_id)
    assert row.status == "expired"


@pytest.mark.asyncio
async def test_drain_only_touches_target_user(db, fake_brain) -> None:
    """A pending intent for u2 should not be drained when u1's toolkit lands."""
    await enqueue_intent(
        user_id="u2", toolkits=["gmail"], intent="for u2 only",
    )
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    fired = await drain_for_toolkit("u1", "gmail")

    assert fired == 0
    assert fake_brain == []


@pytest.mark.asyncio
async def test_drain_marks_failed_when_brain_throws(db, monkeypatch) -> None:
    """If the proactive turn errors, the row goes to status='failed'
    with the error captured — not silently dropped."""
    async def _boom(user_id, intent, intent_id):
        raise RuntimeError("brain blew up")

    monkeypatch.setattr(
        "backend.integrations.pending_intents._fire_proactive_turn",
        _boom,
    )

    intent_id = await enqueue_intent(
        user_id="u1", toolkits=["gmail"], intent="x",
    )
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    fired = await drain_for_toolkit("u1", "gmail")

    assert fired == 0

    from db.models import PendingIntegrationIntent

    async with db() as s:
        row = await s.get(PendingIntegrationIntent, intent_id)
    assert row.status == "failed"
    assert "brain blew up" in (row.last_error or "")


@pytest.mark.asyncio
async def test_enqueue_rejects_empty_inputs(db) -> None:
    assert await enqueue_intent("u1", [], "x") is None
    assert await enqueue_intent("u1", ["gmail"], "") is None
    assert await enqueue_intent("", ["gmail"], "x") is None
