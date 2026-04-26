"""Tests for backend.integrations.notify.notify_integration_complete.

Covers:
- Sends a WhatsApp message to the user's phone
- Dedup: re-firing for the same toolkit within an hour skips
- Re-fires after the dedupe window expires
- bootstrap_summary=True changes the copy (mentions inbox)
- Non-google toolkit gets the simple "<x> connected" copy
- Multiple toolkits in one call get a single message listing them
- Missing user / missing phone -> skipped gracefully
- WA delivery failure does NOT poison the dedupe map (next retry can send)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.integrations import notify
from db.models import User


@pytest_asyncio.fixture
async def user(db):
    """Insert a user with a real phone so notify can pick it up."""
    from backend.db.session import async_session

    uid = "test-user-notify"
    async with async_session() as s:
        u = User(id=uid, phone="+15551234567", living_profile={})
        s.add(u)
        await s.commit()
    yield uid
    async with async_session() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if u is not None:
            await s.delete(u)
            await s.commit()


@pytest.fixture
def stub_wa(monkeypatch):
    """Capture WhatsApp sends without hitting the network."""
    captured = {"sends": []}

    class _FakeWA:
        async def send(self, phone, message):
            captured["sends"].append({"phone": phone, "body": message.body})
            return "wamid.fake"

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel", lambda: _FakeWA()
    )
    return captured


@pytest.mark.asyncio
async def test_sends_to_user_phone(user, stub_wa):
    res = await notify.notify_integration_complete(user, ["slack"])
    assert res["status"] == "sent"
    assert res["sent"] == ["slack"]
    assert stub_wa["sends"]
    assert stub_wa["sends"][0]["phone"] == "+15551234567"
    assert "slack connected" in stub_wa["sends"][0]["body"]


@pytest.mark.asyncio
async def test_dedup_within_window_skips(user, stub_wa):
    """Two consecutive calls for slack should send once, skip the second."""
    first = await notify.notify_integration_complete(user, ["slack"])
    second = await notify.notify_integration_complete(user, ["slack"])
    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert second["reason"] == "all_recently_notified"
    assert len(stub_wa["sends"]) == 1


@pytest.mark.asyncio
async def test_resends_after_dedupe_window(user, stub_wa):
    """A toolkit notified > NOTIFY_DEDUPE_WINDOW_S ago should re-fire."""
    # Plant a stale notified-at timestamp.
    long_ago = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(hours=2)
    ).isoformat()
    await notify._write_notified_map(user, [])  # ensure map exists
    # Manually backdate
    from sqlalchemy.orm.attributes import flag_modified
    from backend.db.session import async_session
    async with async_session() as s:
        u = (await s.execute(select(User).where(User.id == user))).scalar_one()
        profile = dict(u.living_profile or {})
        profile["notified_integrations"] = {"slack": long_ago}
        u.living_profile = profile
        flag_modified(u, "living_profile")
        await s.commit()

    res = await notify.notify_integration_complete(user, ["slack"])
    assert res["status"] == "sent"
    assert stub_wa["sends"]


@pytest.mark.asyncio
async def test_bootstrap_summary_copy_mentions_inbox(user, stub_wa):
    """When called from the bootstrap path with gmail in the toolkits,
    the message references the inbox / having read through it.

    The copy says 'inbox' rather than 'gmail' explicitly — "your inbox"
    is the user-facing word for what just got read; saying "gmail" leaks
    the implementation detail."""
    res = await notify.notify_integration_complete(
        user, ["gmail"], bootstrap_summary=True
    )
    assert res["status"] == "sent"
    body = stub_wa["sends"][0]["body"].lower()
    assert "inbox" in body
    assert "ask me anything" in body


@pytest.mark.asyncio
async def test_multiple_toolkits_single_message(user, stub_wa):
    res = await notify.notify_integration_complete(
        user, ["slack", "notion"]
    )
    assert res["status"] == "sent"
    assert len(stub_wa["sends"]) == 1
    body = stub_wa["sends"][0]["body"]
    assert "slack" in body
    assert "notion" in body


@pytest.mark.asyncio
async def test_partial_dedup_only_sends_fresh_toolkits(user, stub_wa):
    """slack notified earlier, notion fresh -> message only mentions notion."""
    await notify.notify_integration_complete(user, ["slack"])
    stub_wa["sends"].clear()

    res = await notify.notify_integration_complete(user, ["slack", "notion"])
    assert res["status"] == "sent"
    assert res["sent"] == ["notion"]
    assert "slack" in res["skipped"]
    body = stub_wa["sends"][0]["body"]
    assert "notion" in body
    assert "slack" not in body


@pytest.mark.asyncio
async def test_missing_phone_skipped_gracefully(db, stub_wa):
    """User with no phone -> skipped, not an exception."""
    from backend.db.session import async_session
    async with async_session() as s:
        s.add(User(id="user-no-phone", phone=" ", living_profile={}))
        await s.commit()
    # Force phone to empty by patching _user_phone (real model requires
    # non-null/non-blank phone but we want to exercise the empty branch).
    import backend.integrations.notify as nm
    orig = nm._user_phone

    async def _none(uid):
        return None
    nm._user_phone = _none
    try:
        res = await notify.notify_integration_complete(
            "user-no-phone", ["slack"]
        )
    finally:
        nm._user_phone = orig
    assert res["status"] == "skipped"
    assert res["reason"] == "no_phone"
    assert stub_wa["sends"] == []


@pytest.mark.asyncio
async def test_wa_failure_preserves_dedup_map_for_retry(user, monkeypatch):
    """If WA send fails, the dedupe map must NOT be updated — otherwise
    the user would never get the notification on retry."""
    class _BoomWA:
        async def send(self, phone, message):
            raise RuntimeError("WA unreachable")

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel", lambda: _BoomWA()
    )

    res = await notify.notify_integration_complete(user, ["slack"])
    assert res["status"] == "failed"

    # Dedupe map should still be empty so the next retry can send.
    notified = await notify._read_notified_map(user)
    assert notified.get("slack") is None


@pytest.mark.asyncio
async def test_empty_toolkits_is_noop(user, stub_wa):
    res = await notify.notify_integration_complete(user, [])
    assert res["status"] == "noop"
    assert stub_wa["sends"] == []


@pytest.mark.asyncio
async def test_multi_toolkit_with_gmail_uses_bootstrap_copy(user, stub_wa):
    """Bootstrap summary with gmail + calendar should reference the
    inbox-read treatment AND the other toolkit by name."""
    res = await notify.notify_integration_complete(
        user, ["gmail", "googlecalendar"], bootstrap_summary=True
    )
    assert res["status"] == "sent"
    body = stub_wa["sends"][0]["body"].lower()
    assert "inbox" in body
    assert "calendar" in body


# ---------------------------------------------------------------------------
# Two-stage notify (STAGE_CONNECTED vs STAGE_BOOTSTRAPPED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_connected_default_for_immediate_path(user, stub_wa):
    """The watcher / webhook / reconcile paths fire stage=connected
    immediately when OAuth lands. Copy reflects 'reading now', not
    'done reading'."""
    res = await notify.notify_integration_complete(
        user, ["gmail"], stage=notify.STAGE_CONNECTED
    )
    assert res["status"] == "sent"
    assert res["stage"] == notify.STAGE_CONNECTED
    body = stub_wa["sends"][0]["body"].lower()
    assert "reading" in body or "give me a sec" in body
    assert "ask me anything" not in body  # that's the post-bootstrap copy


@pytest.mark.asyncio
async def test_stage_bootstrapped_does_not_dedupe_against_stage_connected(
    user, stub_wa
):
    """User MUST get both pings: the immediate 'gmail's in' AND the
    follow-up 'read through your inbox.' Per-stage dedupe keys make this
    work."""
    res1 = await notify.notify_integration_complete(
        user, ["gmail"], stage=notify.STAGE_CONNECTED
    )
    res2 = await notify.notify_integration_complete(
        user, ["gmail"], stage=notify.STAGE_BOOTSTRAPPED
    )
    assert res1["status"] == "sent"
    assert res2["status"] == "sent"
    assert len(stub_wa["sends"]) == 2
    # Distinct copy
    assert "reading" in stub_wa["sends"][0]["body"].lower()
    assert "ask me anything" in stub_wa["sends"][1]["body"].lower()


@pytest.mark.asyncio
async def test_repeated_same_stage_within_window_dedupes(user, stub_wa):
    """If watcher AND webhook both fire stage=connected for the same
    toolkit within seconds, second call dedupes — user sees one ping,
    not two."""
    res1 = await notify.notify_integration_complete(
        user, ["slack"], stage=notify.STAGE_CONNECTED
    )
    res2 = await notify.notify_integration_complete(
        user, ["slack"], stage=notify.STAGE_CONNECTED
    )
    assert res1["status"] == "sent"
    assert res2["status"] == "skipped"
    assert len(stub_wa["sends"]) == 1


@pytest.mark.asyncio
async def test_stage_connected_copy_for_non_google_toolkit(user, stub_wa):
    """slack landing should say 'connected. on it.' — no mention of
    inbox / reading because there's no bootstrap pipeline behind it."""
    res = await notify.notify_integration_complete(
        user, ["slack"], stage=notify.STAGE_CONNECTED
    )
    assert res["status"] == "sent"
    body = stub_wa["sends"][0]["body"].lower()
    assert "slack" in body
    assert "connected" in body
    assert "inbox" not in body
    assert "reading" not in body
