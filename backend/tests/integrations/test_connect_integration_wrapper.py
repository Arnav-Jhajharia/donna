"""Wrapper-level tests for the donna_runtime connect_integration tool.

These exercise the chat-facing surface — what string the model gets back —
distinct from `test_connect_integration_tool.py` which tests the backend
function. The wrapper is responsible for: rejecting the legacy `products`
key (since the schema only exposes `toolkits`), forwarding the backend's
Donna-voice consent message verbatim, and Donna-voice wrapping the
already_connected / error branches.
"""
from __future__ import annotations

import pytest

from backend.integrations import state


@pytest.fixture
def stub_chain(monkeypatch):
    """Stub the composio_meta calls used by the backend connect_integration
    so we can exercise the wrapper without hitting Composio."""
    captured: dict = {"resolve": None, "initiate": None}

    async def _fake_resolve(*, toolkits, user_id):
        captured["resolve"] = {"toolkits": list(toolkits), "user_id": user_id}
        return {tk: f"ac_{tk}" for tk in toolkits}

    async def _fake_initiate(*, user_id, toolkit_to_auth_config, **_):
        captured["initiate"] = {
            "user_id": user_id,
            "toolkit_to_auth_config": dict(toolkit_to_auth_config),
        }
        chain = [
            {
                "toolkit": tk,
                "auth_config_id": ac,
                "redirect_url": f"https://composio.dev/redirect/{tk}",
                "connected_account_id": f"ca_{tk}",
            }
            for tk, ac in toolkit_to_auth_config.items()
        ]
        return {"first_url": chain[0]["redirect_url"], "chain": chain}

    monkeypatch.setattr(
        "backend.integrations.composio_meta.resolve_auth_configs", _fake_resolve
    )
    monkeypatch.setattr(
        "backend.integrations.composio_meta.initiate_oauth_chain", _fake_initiate
    )
    return captured


@pytest.fixture
def with_user_id(monkeypatch):
    monkeypatch.setattr("donna_runtime.tools._current_user_id", lambda: "u1")


@pytest.mark.asyncio
async def test_wrapper_forwards_consent_line_with_freshness_hint(
    db, stub_chain, with_user_id
) -> None:
    """The chat-facing return is the backend Donna-voice consent line
    plus the freshness hint added in connect_integration._consent_message."""
    from donna_runtime.tools import connect_integration

    out = await connect_integration.handler({"toolkits": ["gmail"]})
    text = out["content"][0]["text"]

    assert "tap:" in text
    assert "https://composio.dev/redirect/gmail" in text
    assert "link's good for a few minutes." in text


@pytest.mark.asyncio
async def test_wrapper_rejects_legacy_products_key(
    db, stub_chain, with_user_id
) -> None:
    """The schema exposes `toolkits` only. If the model passes `products`
    instead, hard-correct it — never silently translate, because the
    backend ALSO accepts a different `products` shape (provider+products)
    and silent fallback hid drift in the past."""
    from donna_runtime.tools import connect_integration

    out = await connect_integration.handler({"products": ["gmail"]})
    text = out["content"][0]["text"]

    assert "takes 'toolkits'" in text
    assert "retry" in text
    # Critically, the backend was NOT called.
    assert stub_chain["resolve"] is None
    assert stub_chain["initiate"] is None


@pytest.mark.asyncio
async def test_wrapper_voice_wraps_already_connected(
    db, stub_chain, with_user_id
) -> None:
    from donna_runtime.tools import connect_integration

    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    out = await connect_integration.handler({"toolkits": ["gmail"]})
    text = out["content"][0]["text"]

    assert text == "already connected. nothing to do."


@pytest.mark.asyncio
async def test_wrapper_voice_wraps_error(monkeypatch, with_user_id) -> None:
    """When the backend returns status='error', the wrapper offers a
    Donna-voice retry hint instead of the raw error string."""
    from donna_runtime.tools import connect_integration

    async def _fake_connect(**kwargs):
        return {"status": "error", "url": None, "message": "composio offline"}

    monkeypatch.setattr(
        "backend.memory.tools.connect_integration.connect_integration",
        _fake_connect,
    )

    out = await connect_integration.handler({"toolkits": ["gmail"]})
    text = out["content"][0]["text"]

    assert "connect failed" in text
    assert "composio offline" in text
    assert "try again in a sec" in text
