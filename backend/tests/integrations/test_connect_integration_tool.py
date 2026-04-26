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
async def test_connect_integration_two_google_toolkits_uses_chain(
    db, stub_chain
) -> None:
    res = await connect_integration(
        user_id="u1", toolkits=["gmail", "googlecalendar"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["gmail", "googlecalendar"]
    assert list(stub_chain["initiate"]["toolkit_to_auth_config"].keys()) == [
        "gmail",
        "googlecalendar",
    ]
    # urls keyed by toolkit slug
    assert res["urls"] == {
        "gmail": "https://composio.dev/redirect/gmail",
        "googlecalendar": "https://composio.dev/redirect/googlecalendar",
    }
    assert res["toolkits"] == ["gmail", "googlecalendar"]
    assert res["url"] == "https://composio.dev/redirect/gmail"
    assert "https://composio.dev/redirect/gmail" in res["message"]
    assert "https://composio.dev/redirect/googlecalendar" not in res["message"]
    assert "one tap" in res["message"]

    # DB rows still labeled provider="google" with friendly products
    gmail_row = await state.get_integration_status("u1", "google", "gmail")
    cal_row = await state.get_integration_status("u1", "google", "calendar")
    assert gmail_row.status == "pending"
    assert cal_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_three_google_toolkits_chain_one_url(
    db, stub_chain
) -> None:
    res = await connect_integration(
        user_id="u1",
        toolkits=["gmail", "googlecalendar", "googledrive"],
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == [
        "gmail",
        "googlecalendar",
        "googledrive",
    ]
    assert res["url"] == "https://composio.dev/redirect/gmail"
    assert res["message"].count("https://") == 1
    assert "gmail + calendar + drive" in res["message"]
    assert set(res["urls"].keys()) == {"gmail", "googlecalendar", "googledrive"}

    drive_row = await state.get_integration_status("u1", "google", "drive")
    assert drive_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_single_toolkit_keeps_old_message(
    db, stub_chain
) -> None:
    res = await connect_integration(user_id="u1", toolkits=["gmail"])

    assert res["status"] == "url_sent"
    assert "https://composio.dev/redirect/gmail" in res["message"]
    assert "tap:" in res["message"]
    assert "one tap" not in res["message"]


@pytest.mark.asyncio
async def test_connect_integration_accepts_friendly_aliases(db, stub_chain) -> None:
    """Friendly aliases ("calendar", "drive") should map to googlecalendar /
    googledrive so the model can pass either form."""
    res = await connect_integration(
        user_id="u1", toolkits=["calendar", "drive"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["googlecalendar", "googledrive"]
    cal_row = await state.get_integration_status("u1", "google", "calendar")
    drive_row = await state.get_integration_status("u1", "google", "drive")
    assert cal_row.status == "pending"
    assert drive_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_non_google_uses_composio_provider(
    db, stub_chain
) -> None:
    """Non-google toolkits should mirror as provider="composio"."""
    res = await connect_integration(user_id="u1", toolkits=["slack"])

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["slack"]
    slack_row = await state.get_integration_status("u1", "composio", "slack")
    assert slack_row.status == "pending"
    # No google row leaked
    google_slack = await state.get_integration_status("u1", "google", "slack")
    assert google_slack is None


@pytest.mark.asyncio
async def test_connect_integration_mixed_toolkits_chain_single_url(
    db, stub_chain
) -> None:
    """Google + non-google in one call should still return ONE URL via chain."""
    res = await connect_integration(
        user_id="u1", toolkits=["gmail", "slack", "notion"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["gmail", "slack", "notion"]
    assert res["message"].count("https://") == 1
    assert "gmail + slack + notion" in res["message"]
    # Mirror state across both providers
    gmail_row = await state.get_integration_status("u1", "google", "gmail")
    slack_row = await state.get_integration_status("u1", "composio", "slack")
    notion_row = await state.get_integration_status("u1", "composio", "notion")
    assert gmail_row.status == "pending"
    assert slack_row.status == "pending"
    assert notion_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_already_connected_short_circuits(
    db, stub_chain
) -> None:
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_existing"
    )

    res = await connect_integration(user_id="u1", toolkits=["gmail"])

    assert res["status"] == "already_connected"
    assert res["url"] is None
    assert stub_chain["resolve"] is None
    assert stub_chain["initiate"] is None


@pytest.mark.asyncio
async def test_connect_integration_legacy_products_kwarg_still_works(
    db, stub_chain
) -> None:
    """Older callers used provider=google, products=[...]. Still accepted."""
    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail", "calendar"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["gmail", "googlecalendar"]


@pytest.mark.asyncio
async def test_connect_integration_dedupes_aliases(db, stub_chain) -> None:
    """gmail + gmail or calendar + googlecalendar should de-dupe."""
    res = await connect_integration(
        user_id="u1", toolkits=["calendar", "googlecalendar", "gmail", "gmail"]
    )

    assert res["status"] == "url_sent"
    assert stub_chain["resolve"]["toolkits"] == ["googlecalendar", "gmail"]


@pytest.mark.asyncio
async def test_connect_integration_returns_cached_url_when_fresh(
    db, stub_chain
) -> None:
    """Re-asking within the freshness window returns the SAME URL without
    burning Composio credits on a fresh chain initiation."""
    first = await connect_integration(
        user_id="u1", toolkits=["gmail", "googlecalendar"]
    )
    assert first["status"] == "url_sent"
    assert first.get("cached") is False
    assert stub_chain["resolve"] is not None  # initiated on first call

    # Reset the capture dicts so we can detect a NO-OP second call.
    stub_chain["resolve"] = None
    stub_chain["initiate"] = None

    second = await connect_integration(
        user_id="u1", toolkits=["gmail", "googlecalendar"]
    )
    assert second["status"] == "url_sent"
    assert second.get("cached") is True
    assert second["url"] == first["url"]
    # Crucially: the chain was NOT re-initiated.
    assert stub_chain["resolve"] is None
    assert stub_chain["initiate"] is None


@pytest.mark.asyncio
async def test_connect_integration_reissues_when_url_stale(
    db, stub_chain, monkeypatch
) -> None:
    """A pending row whose cached URL is older than the freshness window
    should trigger a fresh chain initiation, not return the stale URL."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from db.models import Integration
    from backend.db.session import async_session

    first = await connect_integration(
        user_id="u1", toolkits=["gmail"]
    )
    assert first.get("cached") is False
    original_url = first["url"]

    # Force the cached URL to look stale (5 minutes ago > 4 min window).
    async with async_session() as s:
        row = (await s.execute(
            select(Integration).where(
                Integration.user_id == "u1",
                Integration.product == "gmail",
            )
        )).scalar_one()
        row.redirect_url_issued_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) - timedelta(minutes=5)
        await s.commit()

    stub_chain["resolve"] = None
    stub_chain["initiate"] = None

    second = await connect_integration(user_id="u1", toolkits=["gmail"])
    assert second["status"] == "url_sent"
    assert second.get("cached") is False
    # Chain was re-initiated — same URL by stub-luck (same toolkit) but
    # the call itself was made.
    assert stub_chain["resolve"] is not None
    assert stub_chain["initiate"] is not None


@pytest.mark.asyncio
async def test_connect_integration_partial_connected_caches_remaining(
    db, stub_chain
) -> None:
    """If gmail is already connected and calendar is pending+fresh, asking
    for gmail+calendar returns the cached calendar URL (gmail is excluded
    from the chain because it's done)."""
    # Connect gmail upfront.
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )
    # Now issue a chain for calendar (which seeds redirect_url cache).
    first = await connect_integration(user_id="u1", toolkits=["calendar"])
    assert first.get("cached") is False

    stub_chain["resolve"] = None
    stub_chain["initiate"] = None

    # Re-ask for both; gmail is connected so excluded, calendar's cache hits.
    second = await connect_integration(
        user_id="u1", toolkits=["gmail", "calendar"]
    )
    assert second["status"] == "url_sent"
    assert second.get("cached") is True
    assert second["url"] == first["url"]
    assert stub_chain["initiate"] is None


@pytest.mark.asyncio
async def test_mark_connected_clears_redirect_url(db) -> None:
    """Once a row flips connected, the cached URL is wiped — it points to
    a now-spent OAuth chain that would 404 on tap."""
    await state.upsert_pending(
        "u1", "google", "gmail", redirect_url="https://composio.dev/s/abc"
    )
    row = await state.get_integration_status("u1", "google", "gmail")
    assert row.redirect_url == "https://composio.dev/s/abc"

    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_done"
    )
    row = await state.get_integration_status("u1", "google", "gmail")
    assert row.status == "connected"
    assert row.redirect_url is None
    assert row.redirect_url_issued_at is None


@pytest.mark.asyncio
async def test_upsert_pending_refreshes_url_on_subsequent_call(db) -> None:
    """Calling upsert_pending again with a new URL should refresh the
    cache (used when a stale URL is replaced by a fresh chain)."""
    await state.upsert_pending(
        "u1", "google", "gmail", redirect_url="https://composio.dev/s/old"
    )
    await state.upsert_pending(
        "u1", "google", "gmail", redirect_url="https://composio.dev/s/new"
    )
    row = await state.get_integration_status("u1", "google", "gmail")
    assert row.redirect_url == "https://composio.dev/s/new"
