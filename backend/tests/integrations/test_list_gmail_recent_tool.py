from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.memory.tools.list_gmail_recent import list_gmail_recent
from db.models import EmailMessage


async def _seed(
    db,
    user_id: str,
    msg_id: str,
    hours_ago: int,
    important: bool = False,
) -> None:
    async with db() as s:
        s.add(
            EmailMessage(
                user_id=user_id,
                gmail_message_id=msg_id,
                thread_id=f"t-{msg_id}",
                from_address="a@b.com",
                from_name=None,
                to_addresses=[],
                cc_addresses=[],
                subject=f"subject {msg_id}",
                snippet="snippet",
                ingest_depth="full",
                is_important=important,
                is_starred=False,
                is_sent=False,
                body_stored=False,
                internal_date=(
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(hours=hours_ago)
                ),
                labels=["INBOX", "PRIMARY"],
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_list_gmail_recent_returns_recent_only(db) -> None:
    await _seed(db, "u1", "m1", hours_ago=1)
    await _seed(db, "u1", "m2", hours_ago=10)
    await _seed(db, "u1", "m3", hours_ago=72)

    result = await list_gmail_recent(user_id="u1", within_hours=24, limit=10)
    assert result["status"] == "ok"
    ids = [m["id"] for m in result["payload"]["messages"]]
    assert "m1" in ids and "m2" in ids
    assert "m3" not in ids


@pytest.mark.asyncio
async def test_list_gmail_recent_important_only_filter(db) -> None:
    await _seed(db, "u1", "m1", hours_ago=1, important=False)
    await _seed(db, "u1", "m2", hours_ago=1, important=True)

    result = await list_gmail_recent(
        user_id="u1", within_hours=24, limit=10, important_only=True
    )
    assert result["status"] == "ok"
    ids = [m["id"] for m in result["payload"]["messages"]]
    assert ids == ["m2"]


@pytest.mark.asyncio
async def test_list_gmail_recent_no_hits_when_empty(db) -> None:
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_list_gmail_recent_isolates_per_user(db) -> None:
    await _seed(db, "u1", "m1", hours_ago=1)
    await _seed(db, "u2", "m2", hours_ago=1)
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    ids = [m["id"] for m in result["payload"]["messages"]]
    assert ids == ["m1"]


@pytest.mark.asyncio
async def test_list_gmail_recent_orders_newest_first(db) -> None:
    await _seed(db, "u1", "old", hours_ago=5)
    await _seed(db, "u1", "new", hours_ago=1)
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    ids = [m["id"] for m in result["payload"]["messages"]]
    assert ids == ["new", "old"]
