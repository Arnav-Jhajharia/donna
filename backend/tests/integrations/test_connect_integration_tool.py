from __future__ import annotations

import pytest

from backend.integrations import state
from backend.memory.tools.connect_integration import connect_integration


@pytest.fixture
def stub_manage(monkeypatch):
    captured: dict = {}

    async def _fake(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "results": {
                "gmail": {
                    "toolkit": "gmail",
                    "status": "initiated",
                    "redirect_url": "https://connect.composio.dev/link/g",
                    "auth_config_id": "ac_g",
                },
                "googlecalendar": {
                    "toolkit": "googlecalendar",
                    "status": "initiated",
                    "redirect_url": "https://connect.composio.dev/link/c",
                    "auth_config_id": "ac_c",
                },
            },
        }

    monkeypatch.setattr(
        "backend.integrations.composio_meta.manage_connections", _fake
    )
    return captured


@pytest.mark.asyncio
async def test_connect_integration_returns_urls_and_marks_pending(
    db, stub_manage
) -> None:
    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail", "calendar"]
    )

    assert res["status"] == "url_sent"
    assert "https://connect.composio.dev/link/g" in res["message"]
    assert "https://connect.composio.dev/link/c" in res["message"]
    assert res["urls"] == {
        "gmail": "https://connect.composio.dev/link/g",
        "calendar": "https://connect.composio.dev/link/c",
    }
    assert stub_manage["kwargs"]["toolkits"] == ["gmail", "googlecalendar"]

    gmail_row = await state.get_integration_status("u1", "google", "gmail")
    cal_row = await state.get_integration_status("u1", "google", "calendar")
    assert gmail_row.status == "pending"
    assert cal_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_already_connected_short_circuits(
    db, stub_manage
) -> None:
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_existing"
    )

    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail"]
    )

    assert res["status"] == "already_connected"
    assert res["url"] is None
    assert "kwargs" not in stub_manage  # never called Composio
