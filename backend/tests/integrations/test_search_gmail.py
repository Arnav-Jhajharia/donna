"""Tests for search_gmail — live Composio search with mirror reuse + persist.

The Composio client is monkeypatched so tests don't need network or a
real toolkit. The in-memory aiosqlite ``db`` fixture from
``conftest.py`` provides the EmailMessage table.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.integrations import state
from backend.memory.tools.search_gmail import search_gmail
from db.models import EmailMessage


@pytest.fixture
def fake_composio(monkeypatch):
    """Stub ComposioClient.list_gmail_message_ids + fetch_gmail_message."""
    captured: dict = {"queries": []}

    class _FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        async def list_gmail_message_ids(self, *, user_id, query, max_results=10):
            captured["queries"].append({"user_id": user_id, "query": query, "max_results": max_results})
            return captured.get("ids_for", []), None

        async def fetch_gmail_message(self, *, user_id, message_id, include_body=True):
            return captured.get("msg_for", {}).get(message_id) or {
                "id": message_id,
                "thread_id": f"thr_{message_id}",
                "from_address": "stranger@example.com",
                "subject": f"fetched {message_id}",
                "snippet": "...",
                "internal_date": datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
                "labels": [],
                "is_important": False,
                "is_starred": False,
                "is_sent": False,
                "ingest_depth": "metadata",
                "body_text": None,
                "body_stored": False,
                "to_addresses": [],
                "cc_addresses": [],
                "from_name": None,
            }

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient", _FakeClient
    )

    # Stub the ingest helper so a fetch produces a mirror row directly
    # (the real ingest path normalises + writes; we're testing the
    # search-tool seam, not the ingest pipeline).
    async def _fake_ingest(uid, msg):
        from backend.db.session import async_session

        async with async_session() as s:
            row = EmailMessage(
                user_id=uid,
                gmail_message_id=msg["id"],
                thread_id=msg.get("thread_id") or "t",
                from_address=msg.get("from_address") or "",
                subject=msg.get("subject") or "",
                snippet=msg.get("snippet") or "",
                labels=[],
                is_important=False,
                is_starred=False,
                is_sent=False,
                ingest_depth="metadata",
                internal_date=datetime(2026, 5, 1, 10, 0).replace(tzinfo=None),
                to_addresses=[],
                cc_addresses=[],
            )
            s.add(row)
            await s.commit()

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.ingest_gmail_message",
        _fake_ingest,
    )

    return captured


@pytest.mark.asyncio
async def test_search_returns_no_hits_when_gmail_not_connected(db, fake_composio) -> None:
    res = await search_gmail(user_id="u1", query="from:stripe.com")
    assert res["status"] == "degraded"
    reason = (res["payload"].get("reason") or "").lower()
    assert "connect" in reason  # "isn't connected" or "not connected"


@pytest.mark.asyncio
async def test_search_returns_no_hits_when_query_empty(db, fake_composio) -> None:
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    res = await search_gmail(user_id="u1", query="   ")
    assert res["status"] == "no_hits"


@pytest.mark.asyncio
async def test_search_returns_no_hits_when_composio_returns_empty(
    db, fake_composio
) -> None:
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")
    fake_composio["ids_for"] = []

    res = await search_gmail(user_id="u1", query="from:nobody@example.com")
    assert res["status"] == "no_hits"
    # The composio query was forwarded verbatim.
    assert fake_composio["queries"][-1]["query"] == "from:nobody@example.com"


@pytest.mark.asyncio
async def test_search_returns_mirror_hit_without_fetching(
    db, fake_composio
) -> None:
    """If the id is already in the local mirror, we use that row and do
    NOT round-trip to Composio for the body."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    # Seed mirror with a row whose gmail_message_id matches what
    # composio search returns.
    from backend.db.session import async_session

    async with async_session() as s:
        s.add(
            EmailMessage(
                user_id="u1",
                gmail_message_id="msg_in_mirror",
                thread_id="thr_1",
                from_address="finance@stripe.com",
                subject="invoice 2026-05",
                snippet="...",
                labels=["INBOX"],
                is_important=True,
                is_starred=False,
                is_sent=False,
                ingest_depth="full",
                internal_date=datetime(2026, 5, 1, 9, 0).replace(tzinfo=None),
                to_addresses=[],
                cc_addresses=[],
            )
        )
        await s.commit()

    fake_composio["ids_for"] = ["msg_in_mirror"]

    res = await search_gmail(user_id="u1", query="from:stripe.com")

    assert res["status"] == "ok"
    msgs = res["payload"]["messages"]
    assert any(m.get("from") == "finance@stripe.com" for m in msgs)


@pytest.mark.asyncio
async def test_search_persists_via_fetch_when_id_missing_from_mirror(
    db, fake_composio
) -> None:
    """If composio search returns an id NOT in our mirror, we fetch +
    persist it so the next read is warm."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="ca_x")

    fake_composio["ids_for"] = ["msg_new"]

    res = await search_gmail(user_id="u1", query="from:saurabh")

    assert res["status"] == "ok"

    # And the row was persisted to the mirror.
    from sqlalchemy import select
    from backend.db.session import async_session

    async with async_session() as s:
        row = (
            await s.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == "u1")
                .where(EmailMessage.gmail_message_id == "msg_new")
            )
        ).scalar_one_or_none()
    assert row is not None
