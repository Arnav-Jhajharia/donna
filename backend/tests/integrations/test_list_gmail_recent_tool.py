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


# --- bootstrap-aware empty-mirror behavior ---------------------------------


async def _connect_gmail(db, user_id: str) -> None:
    """Insert a connected google_gmail integration row for the user."""
    from backend.integrations import state
    await state.upsert_pending(user_id, "google", "gmail")
    await state.mark_connected(
        user_id, "google", "gmail", connection_id="ca_test"
    )


async def _set_bootstrap_status(db, user_id: str, status: str | None) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from sqlalchemy import select
    from db.models import User
    async with db() as s:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
        prof = dict(u.living_profile or {})
        if status is None:
            prof.pop("bootstrap_runs", None)
        else:
            prof["bootstrap_runs"] = {"last_status": status}
        u.living_profile = prof
        flag_modified(u, "living_profile")
        await s.commit()


@pytest.mark.asyncio
async def test_no_hits_when_gmail_not_connected_at_all(db) -> None:
    """User has no integration row at all -> tool returns no_hits (the
    legitimate 'this person never connected gmail' case)."""
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_degrades_when_connected_but_bootstrap_never_ran(db) -> None:
    """Critical case from real incident: gmail integration is green but
    bootstrap was never spawned (webhook missed, watcher killed). Donna
    must NOT lie that the inbox is empty.

    The `reason` payload is the user-facing Donna-voice line — it tells
    the user the connection is fresh, not broken.
    """
    await _connect_gmail(db, "u1")
    # No bootstrap_runs entry written.
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "degraded"
    reason = result["payload"]["reason"].lower()
    assert "connected but" in reason
    assert "haven't pulled" in reason


@pytest.mark.asyncio
async def test_degrades_when_bootstrap_running(db) -> None:
    await _connect_gmail(db, "u1")
    await _set_bootstrap_status(db, "u1", "running")
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "degraded"
    reason = result["payload"]["reason"].lower()
    assert "still pulling" in reason
    assert "30-60 seconds" in reason


@pytest.mark.asyncio
async def test_degrades_when_bootstrap_failed(db) -> None:
    await _connect_gmail(db, "u1")
    await _set_bootstrap_status(db, "u1", "failed")
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "degraded"
    reason = result["payload"]["reason"].lower()
    assert "snag" in reason
    assert "retry" in reason


@pytest.mark.asyncio
async def test_no_hits_after_bootstrap_completed_with_empty_window(db) -> None:
    """bootstrap completed + zero recent mail = legitimately empty.
    Returns no_hits (not degraded) so Donna can honestly say 'nothing
    new'."""
    await _connect_gmail(db, "u1")
    await _set_bootstrap_status(db, "u1", "completed")
    result = await list_gmail_recent(user_id="u1", within_hours=24)
    assert result["status"] == "no_hits"
