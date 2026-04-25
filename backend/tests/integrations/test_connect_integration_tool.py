from __future__ import annotations

import pytest

from backend.integrations import state
from backend.memory.tools.connect_integration import connect_integration


@pytest.fixture
def stub_chain(monkeypatch):
    """Stub composio_meta.resolve_auth_configs + initiate_oauth_chain.

    The fake chain produces one redirect_url per toolkit, in input order,
    and exposes capture dicts so tests can assert call shapes.
    """
    captured: dict = {"resolve": None, "initiate": None}

    async def _fake_resolve(*, toolkits, user_id):
        captured["resolve"] = {"toolkits": list(toolkits), "user_id": user_id}
        # Map each toolkit to a synthetic auth_config_id, in input order.
        return {tk: f"ac_{tk}" for tk in toolkits}

    async def _fake_initiate(
        *, user_id, toolkit_to_auth_config, final_callback_url=None
    ):
        captured["initiate"] = {
            "user_id": user_id,
            "toolkit_to_auth_config": dict(toolkit_to_auth_config),
            "final_callback_url": final_callback_url,
        }
        chain = []
        for toolkit, ac_id in toolkit_to_auth_config.items():
            chain.append(
                {
                    "toolkit": toolkit,
                    "auth_config_id": ac_id,
                    "redirect_url": f"https://composio.dev/redirect/{toolkit}",
                    "connected_account_id": f"ca_{toolkit}",
                }
            )
        return {"first_url": chain[0]["redirect_url"], "chain": chain}

    monkeypatch.setattr(
        "backend.integrations.composio_meta.resolve_auth_configs", _fake_resolve
    )
    monkeypatch.setattr(
        "backend.integrations.composio_meta.initiate_oauth_chain", _fake_initiate
    )
    return captured


@pytest.mark.asyncio
async def test_connect_integration_two_products_uses_chain(db, stub_chain) -> None:
    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail", "calendar"]
    )

    assert res["status"] == "url_sent"
    # Toolkit ordering -> gmail, googlecalendar
    assert stub_chain["resolve"]["toolkits"] == ["gmail", "googlecalendar"]
    # Chain initiated with the resolved auth configs in the same order
    assert list(stub_chain["initiate"]["toolkit_to_auth_config"].keys()) == [
        "gmail",
        "googlecalendar",
    ]
    # Per-product url map (back-compat)
    assert res["urls"] == {
        "gmail": "https://composio.dev/redirect/gmail",
        "calendar": "https://composio.dev/redirect/googlecalendar",
    }
    # Primary URL = first toolkit's redirect_url
    assert res["url"] == "https://composio.dev/redirect/gmail"
    # Chain message exposes ONLY the first URL (not all of them)
    assert "https://composio.dev/redirect/gmail" in res["message"]
    assert "https://composio.dev/redirect/googlecalendar" not in res["message"]
    assert "one tap" in res["message"]

    gmail_row = await state.get_integration_status("u1", "google", "gmail")
    cal_row = await state.get_integration_status("u1", "google", "calendar")
    assert gmail_row.status == "pending"
    assert cal_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_three_products_chain_one_url(
    db, stub_chain
) -> None:
    res = await connect_integration(
        user_id="u1",
        provider="google",
        products=["gmail", "calendar", "drive"],
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == [
        "gmail",
        "googlecalendar",
        "googledrive",
    ]
    assert res["url"] == "https://composio.dev/redirect/gmail"
    # Only ONE URL appears in the consent message, not three
    assert res["message"].count("https://") == 1
    assert "gmail + calendar + drive" in res["message"]
    # Per-product map still has all three for downstream use
    assert set(res["urls"].keys()) == {"gmail", "calendar", "drive"}

    drive_row = await state.get_integration_status("u1", "google", "drive")
    assert drive_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_single_product_keeps_old_message(
    db, stub_chain
) -> None:
    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail"]
    )

    assert res["status"] == "url_sent"
    assert "https://composio.dev/redirect/gmail" in res["message"]
    # Single-product wording, not chain wording
    assert "tap:" in res["message"]
    assert "one tap" not in res["message"]


@pytest.mark.asyncio
async def test_connect_integration_accepts_drive_only(db, stub_chain) -> None:
    res = await connect_integration(
        user_id="u1", provider="google", products=["drive"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["googledrive"]
    assert res["url"] == "https://composio.dev/redirect/googledrive"


@pytest.mark.asyncio
async def test_connect_integration_already_connected_short_circuits(
    db, stub_chain
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
    assert stub_chain["resolve"] is None  # never called Composio
    assert stub_chain["initiate"] is None
