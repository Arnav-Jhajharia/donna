"""Tests for the per-turn Composio reconcile gate in
donna_runtime.context_builder._maybe_reconcile_integrations.

Goal: catch OAuth completions that the background watcher missed (or
hasn't gotten to yet), so the [INTEGRATIONS] block rendered into the
next user turn already shows ground truth — without burning an HTTP
roundtrip on every quiet turn."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations import state
from donna_runtime import context_builder


@pytest.fixture
def reset_reconcile_cache():
    context_builder._LAST_INTEGRATIONS_RECONCILE.clear()
    yield
    context_builder._LAST_INTEGRATIONS_RECONCILE.clear()


@pytest.fixture
def stub_reconcile(monkeypatch):
    """Replace reconcile_with_composio with a counter so we can prove the
    gate fired (or didn't)."""
    captured = {"calls": []}

    async def _fake(user_id, toolkits=None):
        captured["calls"].append({"user_id": user_id, "toolkits": toolkits})
        return {}

    monkeypatch.setattr(
        "backend.memory.tools.check_integration_status.reconcile_with_composio",
        _fake,
    )
    return captured


@pytest.mark.asyncio
async def test_reconcile_fires_when_pending_row_present(
    db, reset_reconcile_cache, stub_reconcile
):
    """Most important case: there's a pending row, reconcile MUST fire so
    the next-turn [INTEGRATIONS] reflects the OAuth that may have just
    completed in the user's browser."""
    await state.upsert_pending("u1", "google", "gmail")
    rows = await state.list_user_integrations("u1")

    await context_builder._maybe_reconcile_integrations("u1", rows)

    assert len(stub_reconcile["calls"]) == 1
    assert stub_reconcile["calls"][0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_reconcile_skipped_when_no_pending_and_recent(
    db, reset_reconcile_cache, stub_reconcile
):
    """All connected + reconciled recently -> skip the HTTP call. This is
    the steady-state hot path that should NOT cost anything."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )
    rows = await state.list_user_integrations("u1")

    # Pretend we reconciled 10 seconds ago.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    context_builder._LAST_INTEGRATIONS_RECONCILE["u1"] = (
        now - timedelta(seconds=10)
    )

    await context_builder._maybe_reconcile_integrations("u1", rows)
    assert stub_reconcile["calls"] == []


@pytest.mark.asyncio
async def test_reconcile_fires_when_stale_even_without_pending(
    db, reset_reconcile_cache, stub_reconcile
):
    """All connected but it's been >2 min since the last reconcile -> fire
    once to catch silent revocations."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )
    rows = await state.list_user_integrations("u1")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 5 minutes ago — well past the 2-minute interval.
    context_builder._LAST_INTEGRATIONS_RECONCILE["u1"] = (
        now - timedelta(minutes=5)
    )

    await context_builder._maybe_reconcile_integrations("u1", rows)
    assert len(stub_reconcile["calls"]) == 1


@pytest.mark.asyncio
async def test_reconcile_fires_first_time_user_has_no_cache_entry(
    db, reset_reconcile_cache, stub_reconcile
):
    """First seen -> no cached timestamp -> fire."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )
    rows = await state.list_user_integrations("u1")

    await context_builder._maybe_reconcile_integrations("u1", rows)
    assert len(stub_reconcile["calls"]) == 1


@pytest.mark.asyncio
async def test_reconcile_timeout_does_not_raise(
    db, reset_reconcile_cache, monkeypatch
):
    """A slow Composio must not stall the turn. Hit the timeout path and
    verify we silently fall through (still allow render to proceed)."""
    import asyncio

    async def _slow(*a, **kw):
        await asyncio.sleep(10)  # > 1.5s timeout
        return {}

    monkeypatch.setattr(
        "backend.memory.tools.check_integration_status.reconcile_with_composio",
        _slow,
    )
    # Force the timeout to be tiny so the test runs fast
    monkeypatch.setattr(
        context_builder, "_INTEGRATIONS_RECONCILE_TIMEOUT_S", 0.05
    )

    await state.upsert_pending("u1", "google", "gmail")
    rows = await state.list_user_integrations("u1")

    # Should not raise even though the reconcile times out.
    await context_builder._maybe_reconcile_integrations("u1", rows)


@pytest.mark.asyncio
async def test_reconcile_records_timestamp_only_on_success(
    db, reset_reconcile_cache, monkeypatch
):
    """Failed reconcile must NOT update the cache — otherwise we'd skip
    re-trying for 2 minutes after every transient blip."""
    async def _boom(*a, **kw):
        raise RuntimeError("composio down")

    monkeypatch.setattr(
        "backend.memory.tools.check_integration_status.reconcile_with_composio",
        _boom,
    )

    await state.upsert_pending("u1", "google", "gmail")
    rows = await state.list_user_integrations("u1")

    await context_builder._maybe_reconcile_integrations("u1", rows)
    assert "u1" not in context_builder._LAST_INTEGRATIONS_RECONCILE
