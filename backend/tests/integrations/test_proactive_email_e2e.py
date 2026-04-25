"""End-to-end: webhook fires -> ingest -> score -> brain invocation."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import ProactivePing, User


def _sign(body: bytes, secret: str = "topsecret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def client(monkeypatch, db) -> AsyncClient:
    from config import settings as _settings

    monkeypatch.setattr(_settings, "composio_webhook_secret", "topsecret")
    monkeypatch.setattr(_settings, "composio_api_key", "test-key")

    from api.composio_webhook import router

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_webhook_to_proactive_ping(client, db, monkeypatch) -> None:
    # Decorate the seeded u1 with a biography mentioning Sarah at weekly cadence.
    async with db() as s:
        u = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
        u.living_profile = {
            "biography": {
                "relationships": [
                    {
                        "name": "Sarah",
                        "frequency": "weekly",
                        "kind": "colleague",
                        "_email": "sarah@acme.com",
                    },
                ],
            },
        }
        await s.commit()

    # Mock Composio fetch to return an email from sarah, IMPORTANT-flagged.
    async def fake_fetch(self, user_id, message_id, include_body=True):
        return NormalizedGmailMessage(
            gmail_message_id=message_id,
            thread_id="t1",
            from_address="sarah@acme.com",
            from_name="Sarah",
            to_addresses=["you@y.com"],
            cc_addresses=[],
            subject="re: term sheet",
            snippet="signed",
            body_text="all good, see attached.",
            labels=["INBOX", "PRIMARY", "IMPORTANT"],
            is_important=True,
            is_starred=False,
            is_sent=False,
            internal_date=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    # Mock the brain to record the call without actually running.
    invoked: dict = {}

    async def fake_brain(state, config=None):
        invoked["mode"] = config.mode if config else None
        invoked["user_message"] = state["user_message"]
        return state

    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger._invoke_brain",
        fake_brain,
    )

    body = json.dumps(
        {
            "event": "gmail.new_message",
            "user_id": "u1",
            "message_id": "m_critical",
        }
    ).encode()
    r = await client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    # Brain was invoked in proactive mode with the trigger prompt.
    assert invoked["mode"] == "proactive"
    assert "term sheet" in invoked["user_message"].lower()

    # Ping was recorded as fired (not suppressed).
    async with db() as s:
        rows = (
            await s.execute(
                select(ProactivePing).where(ProactivePing.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].suppressed_reason is None
    assert rows[0].source == "email"
    assert rows[0].message_ref == "m_critical"
