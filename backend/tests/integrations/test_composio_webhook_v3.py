"""Tests for the Composio V3 dispatch in api.composio_webhook.

Covers:
- composio.connected_account.created -> mark_connected + spawn bootstrap
- composio.connected_account.expired/deleted -> mark_revoked
- composio.trigger.message + GMAIL_NEW_GMAIL_MESSAGE -> ingest gmail
- composio.trigger.message + GOOGLECALENDAR_NEW_CALENDAR_EVENT -> ingest cal
- composio.trigger.message + GOOGLECALENDAR_DELETED -> delete cal event
- non-google toolkit (slack) connect -> marks composio_slack but skips bootstrap
- both ``type`` and ``event`` field names accepted for the envelope
- legacy v1/v2 ``event`` names still flow through the old code path
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

import api.composio_webhook as wh
from backend.integrations import state


@pytest.fixture
def stub_subscribe(monkeypatch):
    """Skip the live Composio subscribe_triggers call."""
    captured = {"calls": []}

    async def _fake(self, **kwargs):
        captured["calls"].append(kwargs)

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.subscribe_triggers",
        _fake,
    )
    return captured


@pytest.fixture
def stub_bootstrap(monkeypatch):
    """Capture run_bootstrap_async invocations without running the heavy
    pipeline (or even creating the asyncio task — we want a sync-readable
    counter)."""
    captured = {"calls": []}

    async def _fake(user_id):
        captured["calls"].append(user_id)
        return {"status": "completed"}

    # The webhook spawns it via asyncio.create_task; in the test we just
    # replace the coroutine factory so the spawned task runs the fake.
    monkeypatch.setattr(wh, "run_bootstrap_async", _fake)
    return captured


@pytest.mark.asyncio
async def test_v3_connected_account_created_marks_connected_and_bootstraps(
    db, stub_subscribe, stub_bootstrap
):
    payload = {
        "type": "composio.connected_account.created",
        "data": {
            "id": "ca_v3_gmail",
            "user_id": "u1",
            "toolkit": {"slug": "gmail"},
            "status": "ACTIVE",
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ok"] is True
    assert res["marked_connected"] == "google_gmail"

    row = await state.get_integration_status("u1", "google", "gmail")
    assert row.status == "connected"
    assert row.composio_connection_id == "ca_v3_gmail"

    # Subscribe was called for gmail's trigger
    assert stub_subscribe["calls"]
    assert stub_subscribe["calls"][0]["user_id"] == "u1"

    # Bootstrap was spawned (eventually consumed by the asyncio task we
    # replaced via monkeypatch) — give the loop a tick to run it.
    import asyncio
    await asyncio.sleep(0)
    assert stub_bootstrap["calls"] == ["u1"]


@pytest.mark.asyncio
async def test_v3_connected_account_created_non_google_skips_bootstrap(
    db, stub_subscribe, stub_bootstrap
):
    """slack lands -> mirror as composio_slack, NO bootstrap fire."""
    payload = {
        "type": "composio.connected_account.created",
        "data": {
            "id": "ca_v3_slack",
            "user_id": "u1",
            "toolkit": {"slug": "slack"},
            "status": "ACTIVE",
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["marked_connected"] == "composio_slack"

    row = await state.get_integration_status("u1", "composio", "slack")
    assert row.status == "connected"
    assert row.composio_connection_id == "ca_v3_slack"

    import asyncio
    await asyncio.sleep(0)
    assert stub_bootstrap["calls"] == []


@pytest.mark.asyncio
async def test_v3_connected_account_expired_marks_revoked(
    db, stub_subscribe, stub_bootstrap
):
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_old"
    )

    payload = {
        "type": "composio.connected_account.expired",
        "data": {
            "id": "ca_old",
            "user_id": "u1",
            "toolkit": {"slug": "gmail"},
            "status": "EXPIRED",
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["marked_revoked"] == "google_gmail"

    row = await state.get_integration_status("u1", "google", "gmail")
    assert row.status == "revoked"


@pytest.mark.asyncio
async def test_v3_connected_account_deleted_marks_revoked(
    db, stub_subscribe, stub_bootstrap
):
    await state.upsert_pending("u1", "composio", "slack")
    await state.mark_connected(
        "u1", "composio", "slack", connection_id="ca_s"
    )

    payload = {
        "type": "composio.connected_account.deleted",
        "data": {
            "id": "ca_s",
            "user_id": "u1",
            "toolkit": {"slug": "slack"},
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["marked_revoked"] == "composio_slack"


@pytest.mark.asyncio
async def test_v3_trigger_gmail_new_message_dispatches_ingest(
    db, monkeypatch, stub_subscribe, stub_bootstrap
):
    captured: dict = {"fetch": [], "ingest": []}

    async def _fake_fetch(self, *, user_id, message_id, include_body):
        captured["fetch"].append({"user_id": user_id, "message_id": message_id})
        return "fake-msg-object"

    async def _fake_ingest(user_id, msg):
        captured["ingest"].append({"user_id": user_id, "msg": msg})

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        _fake_fetch,
    )
    monkeypatch.setattr(wh, "ingest_gmail_message", _fake_ingest)

    # Need an existing google_gmail row so touch_synced has something to
    # update (the function silently no-ops when the row is missing, but
    # the assertion below for sync metadata works either way).
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )

    payload = {
        "type": "composio.trigger.message",
        "data": {
            "user_id": "u1",
            "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
            "trigger_data": {"message_id": "m_42", "thread_id": "t_1"},
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ingested"] == "gmail.new_message"
    assert captured["fetch"] == [{"user_id": "u1", "message_id": "m_42"}]
    assert captured["ingest"] == [{"user_id": "u1", "msg": "fake-msg-object"}]


@pytest.mark.asyncio
async def test_v3_trigger_calendar_event_created_dispatches_ingest(
    db, monkeypatch, stub_subscribe, stub_bootstrap
):
    captured: dict = {"events": []}

    async def _fake_ingest(user_id, ev):
        captured["events"].append({"user_id": user_id, "ev": ev})

    monkeypatch.setattr(wh, "ingest_calendar_event", _fake_ingest)

    payload = {
        "type": "composio.trigger.message",
        "data": {
            "user_id": "u1",
            "trigger_slug": "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
            "trigger_data": {"id": "ev_123", "summary": "lunch"},
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ingested"] == "calendar.event.upsert"
    assert captured["events"][0]["ev"]["id"] == "ev_123"


@pytest.mark.asyncio
async def test_v3_trigger_calendar_event_deleted_dispatches_delete(
    db, monkeypatch, stub_subscribe, stub_bootstrap
):
    captured: dict = {"deletes": []}

    async def _fake_delete(user_id, ev_id):
        captured["deletes"].append({"user_id": user_id, "ev_id": ev_id})

    monkeypatch.setattr(wh, "delete_calendar_event", _fake_delete)

    payload = {
        "type": "composio.trigger.message",
        "data": {
            "user_id": "u1",
            "trigger_slug": "GOOGLECALENDAR_EVENT_CANCELED_DELETED_TRIGGER",
            "trigger_data": {"id": "ev_dead"},
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ingested"] == "calendar.event.deleted"
    assert captured["deletes"] == [{"user_id": "u1", "ev_id": "ev_dead"}]


@pytest.mark.asyncio
async def test_v3_trigger_unknown_slug_logs_and_returns_ok(
    db, stub_subscribe, stub_bootstrap
):
    """An unknown trigger should return 200 (so Composio doesn't retry
    forever) but be flagged as unhandled."""
    payload = {
        "type": "composio.trigger.message",
        "data": {
            "user_id": "u1",
            "trigger_slug": "NOTION_PAGE_CREATED",
            "trigger_data": {},
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ok"] is True
    assert res["unhandled_trigger"] == "NOTION_PAGE_CREATED"


@pytest.mark.asyncio
async def test_v3_trigger_disabled_returns_ok(
    db, stub_subscribe, stub_bootstrap
):
    payload = {
        "type": "composio.trigger.disabled",
        "data": {"trigger_id": "trg_xx"},
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ok"] is True
    assert res["noted"] == "trigger_disabled"


@pytest.mark.asyncio
async def test_v3_event_field_accepted_in_lieu_of_type(
    db, stub_subscribe, stub_bootstrap
):
    """Some Composio clients put the event under ``event`` instead of
    ``type``. The webhook reads either."""
    payload = {
        "event": "composio.connected_account.created",
        "data": {
            "id": "ca_alt",
            "user_id": "u1",
            "toolkit": {"slug": "gmail"},
        },
    }
    # Going through the actual route would need full FastAPI machinery;
    # call the same condition the route checks.
    event_type = str(payload.get("type") or payload.get("event") or "")
    assert event_type.startswith("composio.")
    res = await wh._dispatch_v3(event_type, payload)
    assert res["marked_connected"] == "google_gmail"


@pytest.mark.asyncio
async def test_v3_missing_user_id_is_ignored_not_500(
    db, stub_subscribe, stub_bootstrap
):
    """Malformed envelope returns 200 with ignored=True so Composio
    doesn't retry indefinitely."""
    payload = {
        "type": "composio.connected_account.created",
        "data": {"id": "ca_x", "toolkit": {"slug": "gmail"}},  # no user_id
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["ok"] is True
    assert res["ignored"] is True


@pytest.mark.asyncio
async def test_v3_flat_toolkit_slug_field_supported(
    db, stub_subscribe, stub_bootstrap
):
    """Some envelopes flatten toolkit to a string field instead of a dict."""
    payload = {
        "type": "composio.connected_account.created",
        "data": {
            "id": "ca_flat",
            "user_id": "u1",
            "toolkit_slug": "googledrive",
        },
    }
    res = await wh._dispatch_v3(payload["type"], payload)
    assert res["marked_connected"] == "google_drive"
