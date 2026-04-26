"""Tests for the idempotency + failure-surfacing wrapper around
api.composio_webhook.run_bootstrap_async.

Goal: when multiple google toolkits land within seconds of each other
(gmail + calendar + drive each fire watcher.bootstrap on going ACTIVE),
we run the expensive biography pipeline ONCE — not three times — and
when it fails the error is persisted to the user's living_profile so
Donna can see and surface it on the next turn.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

import api.composio_webhook as wh
from db.models import User


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


@pytest_asyncio.fixture
async def user(db):
    """Insert a fresh user row so the bootstrap can read/write
    living_profile.bootstrap_runs. Uses the test sessionmaker the `db`
    fixture monkeypatched in (so backend.db.session.async_session points
    at the in-memory sqlite engine)."""
    from backend.db.session import async_session as test_session

    uid = "test-user-bootstrap"
    async with test_session() as s:
        u = User(id=uid, phone="+10000000001", living_profile={})
        s.add(u)
        await s.commit()
    yield uid
    async with test_session() as s:
        u = (await s.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if u is not None:
            await s.delete(u)
            await s.commit()


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace each bootstrap stage with a counter so we can prove it ran
    (or didn't) exactly once."""
    counts = {"today": 0, "30d": 0, "90d": 0, "calendar": 0, "biography": 0}

    async def _today(uid):
        counts["today"] += 1
    async def _30d(uid):
        counts["30d"] += 1
    async def _90d(uid):
        counts["90d"] += 1
        return {"summary": "stub"}
    async def _cal(uid):
        counts["calendar"] += 1
    async def _bio(uid, msgs, agg):
        counts["biography"] += 1

    monkeypatch.setattr(wh, "bootstrap_today_dense", _today)
    monkeypatch.setattr(wh, "bootstrap_30d_important", _30d)
    monkeypatch.setattr(wh, "bootstrap_90d_aggregates", _90d)
    monkeypatch.setattr(wh, "bootstrap_calendar", _cal)
    monkeypatch.setattr(wh, "synthesize_biography", _bio)
    return counts


@pytest.mark.asyncio
async def test_first_run_executes_pipeline_and_marks_completed(
    user, stub_pipeline
):
    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "completed"
    assert all(c == 1 for c in stub_pipeline.values())

    runs = await wh._read_bootstrap_runs(user)
    assert runs["last_status"] == "completed"
    assert runs["last_completed_at"]
    assert runs["last_error"] is None


@pytest.mark.asyncio
async def test_recent_success_skips_duplicate_run(user, stub_pipeline):
    """Second call within an hour should NOT re-run the heavy pipeline."""
    await wh._write_bootstrap_runs(user, {
        "last_status": "completed",
        "last_completed_at": _utcnow_iso(),  # just now
        "last_error": None,
    })

    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "skipped"
    assert res["reason"] == "recent_success"
    assert all(c == 0 for c in stub_pipeline.values())


@pytest.mark.asyncio
async def test_old_success_re_runs(user, stub_pipeline):
    """A successful run from 2 hours ago is past the dedupe window —
    a new request should re-run the pipeline."""
    long_ago = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(hours=2)
    ).isoformat()
    await wh._write_bootstrap_runs(user, {
        "last_status": "completed",
        "last_completed_at": long_ago,
        "last_error": None,
    })

    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "completed"
    assert all(c == 1 for c in stub_pipeline.values())


@pytest.mark.asyncio
async def test_running_status_blocks_concurrent_run(user, stub_pipeline):
    """If another invocation is already running, second caller skips."""
    await wh._write_bootstrap_runs(user, {
        "last_status": "running",
        "last_started_at": _utcnow_iso(),
    })

    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "skipped"
    assert res["reason"] == "already_running"
    assert all(c == 0 for c in stub_pipeline.values())


@pytest.mark.asyncio
async def test_failed_run_surfaces_error_in_living_profile(
    user, stub_pipeline, monkeypatch
):
    """Pipeline failure must (a) NOT swallow the exception silently — record
    it; (b) leave last_status='failed' so Donna can surface it."""
    async def _boom(uid):
        raise RuntimeError("gmail rate-limited")

    monkeypatch.setattr(wh, "bootstrap_30d_important", _boom)

    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "failed"
    assert "rate-limited" in res["error"]

    runs = await wh._read_bootstrap_runs(user)
    assert runs["last_status"] == "failed"
    assert "rate-limited" in runs["last_error"]
    assert runs["last_failed_at"]


@pytest.mark.asyncio
async def test_previous_failure_does_not_block_retry(user, stub_pipeline):
    """If the last status is 'failed', a new call should retry (not skip).
    This is important so Donna can re-trigger after a transient blip."""
    await wh._write_bootstrap_runs(user, {
        "last_status": "failed",
        "last_error": "boom",
        "last_failed_at": _utcnow_iso(),
    })

    res = await wh.run_bootstrap_async(user)
    assert res["status"] == "completed"
    assert all(c == 1 for c in stub_pipeline.values())

    runs = await wh._read_bootstrap_runs(user)
    assert runs["last_status"] == "completed"
    assert runs["last_error"] is None
