from __future__ import annotations

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.integrations import state


def _sign(body: bytes, secret: str = "topsecret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def client(monkeypatch, db) -> AsyncClient:
    from config import settings as _settings

    monkeypatch.setattr(_settings, "composio_webhook_secret", "topsecret")
    from api.composio_webhook import router

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client) -> None:
    body = json.dumps(
        {"event": "connection.complete", "user_id": "u1", "app": "GMAIL"}
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": "deadbeef"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_connection_complete_marks_connected(client, monkeypatch) -> None:
    async def _noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.subscribe_triggers",
        _noop,
    )

    await state.upsert_pending("u1", "google", "calendar")
    await state.upsert_pending("u1", "google", "gmail")

    body = json.dumps(
        {
            "event": "connection.complete",
            "user_id": "u1",
            "connection_id": "ca-1",
            "app": "GMAIL",
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    status = await state.get_integration_status("u1", "google", "gmail")
    assert status is not None
    assert status.status == "connected"
    assert status.composio_connection_id == "ca-1"


@pytest.mark.asyncio
async def test_webhook_revoke_marks_revoked(client) -> None:
    await state.upsert_pending("u1", "google", "calendar")
    await state.mark_connected("u1", "google", "calendar", connection_id="c-old")

    body = json.dumps(
        {"event": "connection.revoked", "user_id": "u1", "app": "GOOGLECALENDAR"}
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    status = await state.get_integration_status("u1", "google", "calendar")
    assert status is not None
    assert status.status == "revoked"


@pytest.mark.asyncio
async def test_webhook_gmail_new_message_ingests(client, db, monkeypatch) -> None:
    from datetime import datetime

    from sqlalchemy import select

    from backend.integrations.composio_client import NormalizedGmailMessage
    from db.models import EmailMessage

    captured: dict = {}

    async def fake_fetch(self, user_id, message_id, include_body=True):
        captured["fetch"] = (user_id, message_id, include_body)
        return NormalizedGmailMessage(
            gmail_message_id=message_id,
            thread_id="t1",
            from_address="a@b.com",
            from_name=None,
            to_addresses=["you@y.com"],
            cc_addresses=[],
            subject="hi",
            snippet="hi",
            body_text="hello",
            labels=["INBOX", "PRIMARY"],
            is_important=False,
            is_starred=False,
            is_sent=False,
            internal_date=datetime(2026, 4, 25),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    body = json.dumps(
        {"event": "gmail.new_message", "user_id": "u1", "message_id": "m-new"}
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    assert captured["fetch"] == ("u1", "m-new", True)

    async with db() as s:
        row = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.user_id == "u1")
            )
        ).scalar_one()
    assert row.gmail_message_id == "m-new"
    assert row.body_text == "hello"


@pytest.mark.asyncio
async def test_webhook_gmail_new_message_requires_message_id(client, db) -> None:
    body = json.dumps({"event": "gmail.new_message", "user_id": "u1"}).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_calendar_event_created_ingests(client, db) -> None:
    from sqlalchemy import select

    from db.models import CalendarEntry

    body = json.dumps(
        {
            "event": "calendar.event.created",
            "user_id": "u1",
            "data": {
                "id": "e1",
                "summary": "standup",
                "start": {"dateTime": "2026-04-25T09:00:00Z"},
                "end": {"dateTime": "2026-04-25T09:30:00Z"},
            },
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    async with db() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.title == "standup"
    assert row.google_event_id == "e1"


@pytest.mark.asyncio
async def test_webhook_calendar_event_updated_upserts(client, db) -> None:
    from sqlalchemy import select

    from db.models import CalendarEntry

    base = {
        "id": "e1",
        "summary": "standup",
        "start": {"dateTime": "2026-04-25T09:00:00Z"},
        "end": {"dateTime": "2026-04-25T09:30:00Z"},
    }
    create_body = json.dumps(
        {"event": "calendar.event.created", "user_id": "u1", "data": base}
    ).encode()
    await client.post(
        "/webhooks/composio",
        content=create_body,
        headers={"x-composio-signature": _sign(create_body)},
    )

    update_body = json.dumps(
        {
            "event": "calendar.event.updated",
            "user_id": "u1",
            "data": {**base, "summary": "retro"},
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=update_body,
        headers={"x-composio-signature": _sign(update_body)},
    )
    assert r.status_code == 200

    async with db() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.title == "retro"


@pytest.mark.asyncio
async def test_webhook_calendar_event_deleted_removes(client, db) -> None:
    from sqlalchemy import select

    from db.models import CalendarEntry

    create_body = json.dumps(
        {
            "event": "calendar.event.created",
            "user_id": "u1",
            "data": {
                "id": "e1",
                "summary": "standup",
                "start": {"dateTime": "2026-04-25T09:00:00Z"},
                "end": {"dateTime": "2026-04-25T09:30:00Z"},
            },
        }
    ).encode()
    await client.post(
        "/webhooks/composio",
        content=create_body,
        headers={"x-composio-signature": _sign(create_body)},
    )

    delete_body = json.dumps(
        {
            "event": "calendar.event.deleted",
            "user_id": "u1",
            "data": {"id": "e1"},
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=delete_body,
        headers={"x-composio-signature": _sign(delete_body)},
    )
    assert r.status_code == 200

    async with db() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_webhook_connection_complete_subscribes_gmail_triggers(
    client, db, monkeypatch
) -> None:
    captured: dict = {}

    async def fake_subscribe(self, user_id, connection_id, trigger_names):
        captured["subscribe"] = (user_id, connection_id, list(trigger_names))

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.subscribe_triggers",
        fake_subscribe,
    )

    await state.upsert_pending("u1", "google", "gmail")

    body = json.dumps(
        {
            "event": "connection.complete",
            "user_id": "u1",
            "connection_id": "ca-1",
            "app": "GMAIL",
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    assert captured["subscribe"][0] == "u1"
    assert captured["subscribe"][1] == "ca-1"
    assert "GMAIL_NEW_GMAIL_MESSAGE" in captured["subscribe"][2]


@pytest.mark.asyncio
async def test_webhook_connection_complete_subscribes_calendar_triggers(
    client, db, monkeypatch
) -> None:
    captured: dict = {}

    async def fake_subscribe(self, user_id, connection_id, trigger_names):
        captured["subscribe"] = (user_id, connection_id, list(trigger_names))

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.subscribe_triggers",
        fake_subscribe,
    )

    await state.upsert_pending("u1", "google", "calendar")

    body = json.dumps(
        {
            "event": "connection.complete",
            "user_id": "u1",
            "connection_id": "ca-2",
            "app": "GOOGLECALENDAR",
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    triggers = captured["subscribe"][2]
    assert "GOOGLECALENDAR_NEW_CALENDAR_EVENT" in triggers
    assert "GOOGLECALENDAR_UPDATED_CALENDAR_EVENT" in triggers
    assert "GOOGLECALENDAR_DELETED_CALENDAR_EVENT" in triggers


@pytest.mark.asyncio
async def test_webhook_calendar_event_requires_id(client, db) -> None:
    body = json.dumps(
        {"event": "calendar.event.created", "user_id": "u1", "data": {}}
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 400
