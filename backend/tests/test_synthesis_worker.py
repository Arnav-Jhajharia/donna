"""Synthesis worker dispatch tests.

Covers the pure scheduling helpers and the per-user dispatch shape.
DB and Haiku integration is out of scope here — exercised via fixtures
in the integration suite.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from zoneinfo import ZoneInfo

from backend.memory.jobs import synthesis_worker as sw


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("UTC"))


def test_last_anchor_today_when_past_anchor():
    now = _local(2026, 4, 26, 10, 0)
    out = sw._last_anchor_local(now, sw.NIGHTLY_FULL_ANCHOR_HOUR)
    assert out.day == 26
    assert out.hour == sw.NIGHTLY_FULL_ANCHOR_HOUR


def test_last_anchor_yesterday_when_before_anchor():
    now = _local(2026, 4, 26, 1, 0)  # 01:00, before 02:00 anchor
    out = sw._last_anchor_local(now, sw.NIGHTLY_FULL_ANCHOR_HOUR)
    assert out.day == 25
    assert out.hour == sw.NIGHTLY_FULL_ANCHOR_HOUR


def test_full_due_when_no_prior_run():
    now = _local(2026, 4, 26, 10, 0)
    assert sw.is_full_due(now_local=now, generated_at=None) is True


def test_full_due_when_prior_run_before_today_anchor():
    now = _local(2026, 4, 26, 10, 0)
    yesterday_evening = "2026-04-25T20:00:00+00:00"
    assert sw.is_full_due(now_local=now, generated_at=yesterday_evening) is True


def test_full_not_due_when_already_ran_today():
    now = _local(2026, 4, 26, 10, 0)
    today_run = "2026-04-26T02:05:00+00:00"
    assert sw.is_full_due(now_local=now, generated_at=today_run) is False


def test_morning_blocked_before_anchor_hour():
    now = _local(2026, 4, 26, 4, 30)  # 04:30, before 05:00 anchor
    assert (
        sw.is_morning_due(now_local=now, yesterday_refreshed_at=None) is False
    )


def test_morning_due_after_anchor_when_no_prior_refresh():
    now = _local(2026, 4, 26, 6, 0)
    assert sw.is_morning_due(now_local=now, yesterday_refreshed_at=None) is True


def test_morning_not_due_when_already_refreshed_today():
    now = _local(2026, 4, 26, 8, 0)
    today_refresh = "2026-04-26T05:10:00+00:00"
    assert (
        sw.is_morning_due(now_local=now, yesterday_refreshed_at=today_refresh)
        is False
    )


def test_morning_due_when_prior_refresh_was_yesterday():
    now = _local(2026, 4, 26, 8, 0)
    yesterday_refresh = "2026-04-25T05:10:00+00:00"
    assert (
        sw.is_morning_due(
            now_local=now, yesterday_refreshed_at=yesterday_refresh
        )
        is True
    )


def test_run_one_dispatches_full_when_due(monkeypatch):
    full_calls: list[str] = []
    morning_calls: list[str] = []

    async def fake_full(uid: str) -> dict | None:
        full_calls.append(uid)
        return None

    async def fake_morning(uid: str) -> dict | None:
        morning_calls.append(uid)
        return None

    # Pin "now" inside the worker to a moment past today's nightly anchor.
    fixed = _local(2026, 4, 26, 6, 0)

    def fake_user_local_now(_tz: str) -> datetime:
        return fixed

    monkeypatch.setattr(sw, "_user_local_now", fake_user_local_now)

    asyncio.run(
        sw._run_one(
            "user-1",
            "UTC",
            living_profile=None,
            full_runner=fake_full,
            morning_runner=fake_morning,
        )
    )

    assert full_calls == ["user-1"]
    # Full pass also writes generated_at + yesterday_refreshed_at, so
    # morning is not also fired in the same dispatch.
    assert morning_calls == []


def test_run_one_dispatches_morning_when_full_already_done(monkeypatch):
    full_calls: list[str] = []
    morning_calls: list[str] = []

    async def fake_full(uid: str) -> dict | None:
        full_calls.append(uid)
        return None

    async def fake_morning(uid: str) -> dict | None:
        morning_calls.append(uid)
        return None

    fixed = _local(2026, 4, 26, 8, 0)

    def fake_user_local_now(_tz: str) -> datetime:
        return fixed

    monkeypatch.setattr(sw, "_user_local_now", fake_user_local_now)

    profile = {
        "generated_at": "2026-04-26T02:05:00+00:00",
        "yesterday_refreshed_at": "2026-04-25T05:00:00+00:00",
    }
    asyncio.run(
        sw._run_one(
            "user-2",
            "UTC",
            living_profile=profile,
            full_runner=fake_full,
            morning_runner=fake_morning,
        )
    )

    assert full_calls == []
    assert morning_calls == ["user-2"]


def test_run_one_skips_when_neither_due(monkeypatch):
    full_calls: list[str] = []
    morning_calls: list[str] = []

    async def fake_full(uid: str) -> dict | None:
        full_calls.append(uid)
        return None

    async def fake_morning(uid: str) -> dict | None:
        morning_calls.append(uid)
        return None

    fixed = _local(2026, 4, 26, 8, 0)

    def fake_user_local_now(_tz: str) -> datetime:
        return fixed

    monkeypatch.setattr(sw, "_user_local_now", fake_user_local_now)

    profile = {
        "generated_at": "2026-04-26T02:05:00+00:00",
        "yesterday_refreshed_at": "2026-04-26T05:10:00+00:00",
    }
    asyncio.run(
        sw._run_one(
            "user-3",
            "UTC",
            living_profile=profile,
            full_runner=fake_full,
            morning_runner=fake_morning,
        )
    )

    assert full_calls == []
    assert morning_calls == []
