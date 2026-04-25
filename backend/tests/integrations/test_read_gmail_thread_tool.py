from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.memory.tools.read_gmail_thread import read_gmail_thread
from db.models import EmailMessage


async def _seed(
    db,
    msg_id: str,
    body: str | None = None,
    *,
    user_id: str = "u1",
    thread_id: str = "t1",
    minutes_offset: int = 0,
) -> None:
    async with db() as s:
        s.add(
            EmailMessage(
                user_id=user_id,
                gmail_message_id=msg_id,
                thread_id=thread_id,
                from_address="a@b.com",
                from_name=None,
                to_addresses=[],
                cc_addresses=[],
                subject="hi",
                snippet="hi",
                body_text=body,
                body_stored=body is not None,
                ingest_depth="full" if body else "metadata",
                is_important=False,
                is_starred=False,
                is_sent=False,
                internal_date=datetime(2026, 4, 25) + timedelta(minutes=minutes_offset),
                labels=["INBOX", "PRIMARY"],
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_read_gmail_thread_returns_stored_bodies(db) -> None:
    await _seed(db, "m1", body="full body 1", minutes_offset=0)
    await _seed(db, "m2", body="full body 2", minutes_offset=1)
    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    assert result["status"] == "ok"
    bodies = [m["body"] for m in result["payload"]["messages"]]
    assert bodies == ["full body 1", "full body 2"]


@pytest.mark.asyncio
async def test_read_gmail_thread_lazy_fetches_missing_body(db, monkeypatch) -> None:
    await _seed(db, "m1", body=None)

    async def fake_fetch(self, user_id, message_id, include_body=True):
        from backend.integrations.composio_client import NormalizedGmailMessage

        return NormalizedGmailMessage(
            gmail_message_id=message_id,
            thread_id="t1",
            from_address="a@b.com",
            from_name=None,
            to_addresses=[],
            cc_addresses=[],
            subject="hi",
            snippet="hi",
            body_text="lazy fetched body",
            labels=["INBOX"],
            is_important=False,
            is_starred=False,
            is_sent=False,
            internal_date=datetime(2026, 4, 25),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    assert result["payload"]["messages"][0]["body"] == "lazy fetched body"

    async with db() as s:
        row = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.gmail_message_id == "m1")
            )
        ).scalar_one()
    assert row.body_stored is True
    assert row.body_text == "lazy fetched body"


@pytest.mark.asyncio
async def test_read_gmail_thread_no_hits_when_thread_empty(db) -> None:
    result = await read_gmail_thread(user_id="u1", thread_id="missing")
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_read_gmail_thread_isolates_per_user(db) -> None:
    await _seed(db, "m1", body="body", user_id="u1")
    await _seed(db, "m2", body="body", user_id="u2")
    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    ids = [m["id"] for m in result["payload"]["messages"]]
    assert ids == ["m1"]


@pytest.mark.asyncio
async def test_read_gmail_thread_falls_back_when_lazy_fetch_fails(
    db, monkeypatch
) -> None:
    await _seed(db, "m1", body=None)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        boom,
    )

    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    assert result["status"] == "ok"
    assert result["payload"]["messages"][0]["body"] is None
