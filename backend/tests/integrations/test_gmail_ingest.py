from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.gmail_ingest import ingest_gmail_message
from db.models import EmailMessage


@pytest.fixture(autouse=True)
def _stub_proactive(monkeypatch):
    """Default-stub the proactive trigger so ingest tests don't bleed into
    the brain. Tests that want to verify the trigger override explicitly."""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email",
        _noop,
        raising=False,
    )


def _msg(**kwargs) -> NormalizedGmailMessage:
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="sarah@x.com",
        from_name="Sarah",
        to_addresses=["you@y.com"],
        cc_addresses=[],
        subject="term sheet",
        snippet="hi",
        body_text="hello full body",
        labels=["INBOX", "PRIMARY"],
        is_important=False,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 25, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    base.update(kwargs)
    return NormalizedGmailMessage(**base)


@pytest.mark.asyncio
async def test_ingest_full_stores_body(db) -> None:
    await ingest_gmail_message("u1", _msg())
    async with db() as s:
        row = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalar_one()
    assert row.ingest_depth == "full"
    assert row.body_stored is True
    assert row.body_text == "hello full body"


@pytest.mark.asyncio
async def test_ingest_metadata_drops_body(db) -> None:
    msg = _msg(labels=["INBOX", "UPDATES"])
    await ingest_gmail_message("u1", msg)
    async with db() as s:
        row = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalar_one()
    assert row.ingest_depth == "metadata"
    assert row.body_stored is False
    assert row.body_text is None


@pytest.mark.asyncio
async def test_ingest_ignore_inserts_nothing(db) -> None:
    msg = _msg(labels=["SPAM"])
    await ingest_gmail_message("u1", msg)
    async with db() as s:
        rows = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_aggregate_inserts_nothing(db) -> None:
    msg = _msg(labels=["INBOX", "PROMOTIONS"])
    await ingest_gmail_message("u1", msg)
    async with db() as s:
        rows = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_is_idempotent(db) -> None:
    await ingest_gmail_message("u1", _msg())
    await ingest_gmail_message("u1", _msg())
    async with db() as s:
        rows = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ingest_label_change_updates_existing(db) -> None:
    """Re-ingest with new labels should refresh fields (e.g. user marks IMPORTANT)."""
    await ingest_gmail_message("u1", _msg())
    upgraded = _msg(labels=["INBOX", "PRIMARY", "IMPORTANT"], is_important=True)
    await ingest_gmail_message("u1", upgraded)
    async with db() as s:
        row = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalar_one()
    assert row.is_important is True
    assert "IMPORTANT" in row.labels


@pytest.mark.asyncio
async def test_ingest_fires_proactive_check(db, monkeypatch) -> None:
    captured = {}

    async def fake_maybe(user_id, msg):
        captured["called"] = (user_id, msg.gmail_message_id)

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email", fake_maybe
    )
    await ingest_gmail_message("u1", _msg())
    assert captured["called"] == ("u1", "m1")


@pytest.mark.asyncio
async def test_ingest_skips_proactive_for_ignored_message(db, monkeypatch) -> None:
    captured = {"called": False}

    async def fake_maybe(user_id, msg):
        captured["called"] = True

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email", fake_maybe
    )
    await ingest_gmail_message("u1", _msg(labels=["SPAM"]))
    assert captured["called"] is False
