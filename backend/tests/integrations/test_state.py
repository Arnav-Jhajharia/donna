from __future__ import annotations

import pytest

from backend.integrations.state import (
    get_integration_status,
    list_user_integrations,
    mark_connected,
    mark_revoked,
    touch_synced,
    upsert_pending,
)


@pytest.mark.asyncio
async def test_upsert_pending_creates_row(db) -> None:
    await upsert_pending("u1", "google", "calendar")
    rows = await list_user_integrations("u1")
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].provider == "google"
    assert rows[0].product == "calendar"


@pytest.mark.asyncio
async def test_upsert_pending_is_idempotent(db) -> None:
    await upsert_pending("u1", "google", "calendar")
    await upsert_pending("u1", "google", "calendar")
    rows = await list_user_integrations("u1")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_mark_connected_flips_status(db) -> None:
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    status = await get_integration_status("u1", "google", "calendar")
    assert status is not None
    assert status.status == "connected"
    assert status.composio_connection_id == "c-1"
    assert status.connected_at is not None


@pytest.mark.asyncio
async def test_mark_revoked_flips_status(db) -> None:
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    await mark_revoked("u1", "google", "calendar")
    status = await get_integration_status("u1", "google", "calendar")
    assert status is not None
    assert status.status == "revoked"


@pytest.mark.asyncio
async def test_touch_synced_updates_timestamp(db) -> None:
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    await touch_synced("u1", "google", "calendar")
    status = await get_integration_status("u1", "google", "calendar")
    assert status is not None
    assert status.last_synced_at is not None
