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
async def test_webhook_connection_complete_marks_connected(client) -> None:
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
