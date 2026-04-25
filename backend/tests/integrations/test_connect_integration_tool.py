from __future__ import annotations

import pytest

from backend.integrations import state
from backend.memory.tools.connect_integration import connect_integration


class FakeComposio:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_or_create_connection(self, user_id: str, app: str) -> tuple[str, str]:
        self.calls.append((user_id, app))
        return f"cid-{app}", f"https://composio/oauth/{app}/start"


@pytest.mark.asyncio
async def test_connect_integration_returns_url_and_marks_pending(monkeypatch, db) -> None:
    fake = FakeComposio()
    monkeypatch.setattr(
        "backend.memory.tools.connect_integration._client",
        lambda: fake,
    )

    result = await connect_integration(
        user_id="u1", provider="google", products=["calendar", "gmail"]
    )

    assert result["status"] == "url_sent"
    assert result["url"].startswith("https://composio/")
    assert "tap" in result["message"].lower()

    rows = await state.list_user_integrations("u1")
    products = {r.product: r.status for r in rows}
    assert products == {"calendar": "pending", "gmail": "pending"}


@pytest.mark.asyncio
async def test_connect_integration_already_connected(monkeypatch, db) -> None:
    await state.upsert_pending("u1", "google", "calendar")
    await state.mark_connected("u1", "google", "calendar", connection_id="c-old")
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="c-old-2")

    fake = FakeComposio()
    monkeypatch.setattr(
        "backend.memory.tools.connect_integration._client",
        lambda: fake,
    )

    result = await connect_integration(
        user_id="u1", provider="google", products=["calendar", "gmail"]
    )

    assert result["status"] == "already_connected"
    assert result["url"] is None
    assert fake.calls == []
