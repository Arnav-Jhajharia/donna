from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from backend.integrations.composio_client import (
    ComposioClient,
    verify_webhook_signature,
)


def test_verify_webhook_signature_v1_legacy_accepts_valid() -> None:
    """Legacy V1/V2 fallback: when no webhook-id/timestamp are passed,
    verify against hex HMAC of the raw body."""
    secret = "topsecret"
    body = b'{"event":"connection.complete"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret) is True


def test_verify_webhook_signature_legacy_rejects_invalid() -> None:
    assert verify_webhook_signature(b"x", "deadbeef", "topsecret") is False


def test_verify_webhook_signature_v3_standard_webhooks_accepts_valid() -> None:
    """Composio V3 follows Standard Webhooks: the signature is
    HMAC-SHA256("{id}.{ts}.{body}", secret) base64-encoded with a
    'v1,' prefix."""
    secret = "topsecret"
    body = b'{"type":"composio.trigger.message"}'
    webhook_id = "msg_abc123"
    webhook_timestamp = "1234567890"
    signed = f"{webhook_id}.{webhook_timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    sig = "v1," + base64.b64encode(digest).decode()
    assert verify_webhook_signature(
        body, sig, secret,
        webhook_id=webhook_id, webhook_timestamp=webhook_timestamp,
    ) is True


def test_verify_webhook_signature_v3_rotation_window_accepts_either() -> None:
    """During key rotation, Composio sends multiple space-separated
    'v1,sig' tokens — any match is acceptance."""
    secret = "newsecret"
    body = b'{"type":"composio.trigger.message"}'
    webhook_id, ts = "msg_rotation", "1700000000"
    signed = f"{webhook_id}.{ts}.".encode() + body
    good = "v1," + base64.b64encode(
        hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()
    sig_header = f"v1,olddead {good}"
    assert verify_webhook_signature(
        body, sig_header, secret,
        webhook_id=webhook_id, webhook_timestamp=ts,
    ) is True


def test_verify_webhook_signature_v3_rejects_wrong_secret() -> None:
    secret = "topsecret"
    body = b'{"x": 1}'
    webhook_id, ts = "msg_x", "1234567890"
    signed = f"{webhook_id}.{ts}.".encode() + body
    sig = "v1," + base64.b64encode(
        hmac.new(b"wrong", signed, hashlib.sha256).digest()
    ).decode()
    assert verify_webhook_signature(
        body, sig, secret,
        webhook_id=webhook_id, webhook_timestamp=ts,
    ) is False


@pytest.mark.asyncio
async def test_get_or_create_connection_returns_url(monkeypatch) -> None:
    """Wrapper composes a Composio call and returns (connection_id, url).

    Mock matches the real SDK contract: `Toolkits.authorize(*, user_id, toolkit)`
    returns a `ConnectionRequest` exposing `id` + `redirect_url`.
    """
    captured: dict = {}

    class FakeToolkits:
        def authorize(self, *, user_id, toolkit):
            captured["kwargs"] = {"user_id": user_id, "toolkit": toolkit}

            class R:
                id = "ca_123"
                redirect_url = "https://composio/oauth/google/abc"
                status = "INITIATED"

            return R()

    class FakeComposio:
        toolkits = FakeToolkits()

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio", lambda: FakeComposio()
    )
    client = ComposioClient(api_key="x")
    cid, url = await client.get_or_create_connection(user_id="u1", app="GMAIL")
    assert cid == "ca_123"
    assert url.startswith("https://composio/")
    assert captured["kwargs"] == {"user_id": "u1", "toolkit": "GMAIL"}


@pytest.mark.asyncio
async def test_fetch_gmail_message_normalizes_payload(monkeypatch) -> None:
    raw = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX", "IMPORTANT"],
        "snippet": "hi",
        "internalDate": "1714000000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sarah <sarah@x.com>"},
                {"name": "To", "value": "you@y.com"},
                {"name": "Subject", "value": "term sheet"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "aGVsbG8="}},
            ],
        },
    }

    class FakeTools:
        def execute(self, name, user_id, arguments, **_kw):
            return {"data": raw}

    class FakeComposio:
        tools = FakeTools()

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio", lambda: FakeComposio()
    )

    client = ComposioClient(api_key="x")
    msg = await client.fetch_gmail_message(
        user_id="u1", message_id="m1", include_body=True
    )
    assert msg.gmail_message_id == "m1"
    assert msg.thread_id == "t1"
    assert msg.from_address == "sarah@x.com"
    assert msg.from_name == "Sarah"
    assert msg.subject == "term sheet"
    assert "hello" in (msg.body_text or "")
    assert msg.is_important is True
    assert "IMPORTANT" in msg.labels


@pytest.mark.asyncio
async def test_fetch_gmail_message_normalizes_v3_shape(monkeypatch) -> None:
    """Composio's renamed slug (GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID) returns
    a different envelope: top-level messageId/messageText/preview/sender/
    subject/to/labelIds/messageTimestamp instead of the old
    id/threadId/snippet/internalDate + headers-only shape. Normalize must
    handle both."""
    raw = {
        "messageId": "m_v3",
        "threadId": "t_v3",
        "labelIds": ["INBOX", "IMPORTANT"],
        "preview": {"body": "hi from preview", "subject": "term sheet"},
        "messageTimestamp": "2026-04-26T08:32:40Z",
        "messageText": "Hello body text from messageText",
        "sender": "Sarah <sarah@x.com>",
        "subject": "term sheet",
        "to": ["you@y.com"],
        "payload": {"headers": []},
    }

    class FakeTools:
        def execute(self, name, user_id, arguments, **_kw):
            return {"data": raw}

    class FakeComposio:
        tools = FakeTools()

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio", lambda: FakeComposio()
    )

    client = ComposioClient(api_key="x")
    msg = await client.fetch_gmail_message(
        user_id="u1", message_id="m_v3", include_body=True
    )
    assert msg.gmail_message_id == "m_v3"
    assert msg.thread_id == "t_v3"
    assert msg.from_address == "sarah@x.com"
    assert msg.from_name == "Sarah"
    assert msg.subject == "term sheet"
    assert msg.to_addresses == ["you@y.com"]
    assert "Hello body text" in (msg.body_text or "")
    assert msg.is_important is True
    # Preview dict -> snippet should be the body string, not the dict
    assert msg.snippet == "hi from preview"
    assert isinstance(msg.snippet, str)


@pytest.mark.asyncio
async def test_normalize_handles_string_preview(monkeypatch) -> None:
    """Older Composio responses sent ``preview`` as a string, not a dict."""
    raw = {
        "messageId": "m1",
        "threadId": "t1",
        "labelIds": [],
        "preview": "just a string preview",
        "messageText": "body",
        "sender": "x@y.com",
        "subject": "subj",
        "to": [],
        "payload": {"headers": []},
    }

    class FakeTools:
        def execute(self, name, user_id, arguments, **_kw):
            return {"data": raw}

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio",
        lambda: type("F", (), {"tools": FakeTools()})(),
    )

    client = ComposioClient(api_key="x")
    msg = await client.fetch_gmail_message(
        user_id="u1", message_id="m1", include_body=True
    )
    assert msg.snippet == "just a string preview"


@pytest.mark.asyncio
async def test_list_gmail_handles_message_id_field(monkeypatch) -> None:
    """GMAIL_FETCH_EMAILS returns ``messages: [{messageId, threadId, ...}]``;
    older slug returned ``messages: [{id, threadId, ...}]``. Accept both."""
    class FakeTools:
        def execute(self, name, user_id, arguments, **_kw):
            return {
                "data": {
                    "messages": [
                        {"messageId": "m1", "threadId": "t1"},
                        {"id": "m2", "threadId": "t2"},  # legacy field
                        {"messageId": "", "threadId": "t3"},  # filter empty
                    ],
                    "nextPageToken": "",
                }
            }

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio",
        lambda: type("F", (), {"tools": FakeTools()})(),
    )

    client = ComposioClient(api_key="x")
    ids, token = await client.list_gmail_message_ids(user_id="u1", query="x")
    assert ids == ["m1", "m2"]
    assert token is None  # empty string normalized to None


@pytest.mark.asyncio
async def test_subscribe_triggers_uses_create_not_subscribe(monkeypatch) -> None:
    """V3 split the API: triggers.subscribe() takes only `timeout` and
    is for receiving websocket events. triggers.create() actually
    registers a trigger instance. Our wrapper must call create() — the
    silent-swallow on subscribe() failure was the reason no Composio
    webhooks ever fired for any user. Lock this in."""
    captured: dict = {"create_calls": [], "subscribe_calls": 0}

    class FakeTriggers:
        def create(self, slug, *, user_id, connected_account_id, trigger_config=None):
            captured["create_calls"].append({
                "slug": slug,
                "user_id": user_id,
                "connected_account_id": connected_account_id,
            })
            return type("R", (), {"id": f"ti_{slug[:6]}"})

        def subscribe(self, *args, **kwargs):
            captured["subscribe_calls"] += 1
            raise AssertionError(
                "subscribe() must NOT be called — use create() for trigger "
                "instances; subscribe() is the websocket receiver."
            )

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio",
        lambda: type("F", (), {"triggers": FakeTriggers()})(),
    )

    client = ComposioClient(api_key="x")
    ids = await client.subscribe_triggers(
        user_id="u1",
        connection_id="ca_1",
        trigger_names=["GMAIL_NEW_GMAIL_MESSAGE"],
    )
    assert len(captured["create_calls"]) == 1
    assert captured["create_calls"][0]["slug"] == "GMAIL_NEW_GMAIL_MESSAGE"
    assert captured["create_calls"][0]["connected_account_id"] == "ca_1"
    assert captured["subscribe_calls"] == 0
    assert ids and ids[0].startswith("ti_")


@pytest.mark.asyncio
async def test_subscribe_triggers_continues_on_per_slug_failure(monkeypatch):
    """If one slug 404s (e.g. renamed in V3), the others should still
    register — partial trigger coverage beats none."""
    captured: dict = {"create_calls": []}

    class FakeTriggers:
        def create(self, slug, *, user_id, connected_account_id, trigger_config=None):
            captured["create_calls"].append(slug)
            if slug == "BROKEN_SLUG":
                raise RuntimeError("404 Tool not found")
            return type("R", (), {"id": f"ti_{slug[:8]}"})

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio",
        lambda: type("F", (), {"triggers": FakeTriggers()})(),
    )

    client = ComposioClient(api_key="x")
    ids = await client.subscribe_triggers(
        user_id="u1",
        connection_id="ca_1",
        trigger_names=["GMAIL_NEW_GMAIL_MESSAGE", "BROKEN_SLUG", "OTHER_OK"],
    )
    # All three were attempted
    assert captured["create_calls"] == [
        "GMAIL_NEW_GMAIL_MESSAGE", "BROKEN_SLUG", "OTHER_OK"
    ]
    # Two successful registrations returned
    assert len(ids) == 2
