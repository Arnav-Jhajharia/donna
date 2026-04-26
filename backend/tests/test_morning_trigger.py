"""Morning proactive trigger gate tests.

Each test pins ``now_local`` and shapes the living_profile to walk
one branch of the gate logic. We never reach the brain or WhatsApp —
these tests verify the decision layer only.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.web.proactive.triggers.morning import (
    MorningTriggerDecision,
    _inside_window,
    _last_fired_passes_anchor,
    _local_anchor_today,
    maybe_fire_morning_check_in,
)


SGT = ZoneInfo("Asia/Singapore")


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SGT)


def test_inside_window_basic():
    now = _at(2026, 4, 27, 7, 45)
    assert _inside_window(now, "07:30-08:30") is True


def test_inside_window_with_fudge_factor():
    """+/- 30 min fudge so the worker's 5-min poll never misses."""
    now = _at(2026, 4, 27, 8, 50)
    assert _inside_window(now, "07:30-08:30") is True


def test_outside_window_far_after():
    now = _at(2026, 4, 27, 14, 30)
    assert _inside_window(now, "07:30-08:30") is False


def test_inside_window_invalid_string():
    now = _at(2026, 4, 27, 7, 45)
    assert _inside_window(now, "not a window") is False
    assert _inside_window(now, "") is False


def test_last_fired_passes_anchor_when_never_fired():
    anchor = _local_anchor_today(_at(2026, 4, 27, 7, 45))
    assert _last_fired_passes_anchor(None, anchor) is True


def test_last_fired_blocks_when_fired_after_anchor():
    """Fired today after 05:00 → block."""
    anchor = _local_anchor_today(_at(2026, 4, 27, 7, 45))
    last = _at(2026, 4, 27, 5, 30).astimezone(timezone.utc).isoformat()
    assert _last_fired_passes_anchor(last, anchor) is False


def test_last_fired_passes_when_fired_before_anchor():
    """Fired yesterday → pass."""
    anchor = _local_anchor_today(_at(2026, 4, 27, 7, 45))
    last = _at(2026, 4, 26, 7, 30).astimezone(timezone.utc).isoformat()
    assert _last_fired_passes_anchor(last, anchor) is True


@pytest.mark.asyncio
async def test_cold_start_when_rhythm_is_thin():
    """No engage window or wake window in rhythm → cold start gate fires."""
    decision = await maybe_fire_morning_check_in(
        user_id="u1",
        timezone_name="Asia/Singapore",
        living_profile={"rhythm": {}},
        now_local=_at(2026, 4, 27, 7, 45),
    )
    assert decision.fired is False
    assert decision.reason == "cold_start"


@pytest.mark.asyncio
async def test_outside_window_returns_outside_window():
    profile = {
        "rhythm": {
            "typical_first_engage_window": "07:30-08:30",
            "typical_wake_window": "06:30-07:30",
        },
        "watch_for_tomorrow": ["principal follow-up"],
    }
    decision = await maybe_fire_morning_check_in(
        user_id="u1",
        timezone_name="Asia/Singapore",
        living_profile=profile,
        now_local=_at(2026, 4, 27, 14, 0),
    )
    assert decision.fired is False
    assert decision.reason == "outside_window"


@pytest.mark.asyncio
async def test_no_watch_returns_no_watch():
    profile = {
        "rhythm": {
            "typical_first_engage_window": "07:30-08:30",
            "typical_wake_window": "06:30-07:30",
        },
        "watch_for_tomorrow": [],
    }
    decision = await maybe_fire_morning_check_in(
        user_id="u1",
        timezone_name="Asia/Singapore",
        living_profile=profile,
        now_local=_at(2026, 4, 27, 7, 45),
    )
    assert decision.fired is False
    assert decision.reason == "no_watch"


@pytest.mark.asyncio
async def test_already_fired_today_returns_already_fired():
    fired_iso = _at(2026, 4, 27, 7, 30).astimezone(timezone.utc).isoformat()
    profile = {
        "rhythm": {
            "typical_first_engage_window": "07:30-08:30",
            "typical_wake_window": "06:30-07:30",
        },
        "watch_for_tomorrow": ["principal follow-up"],
        "morning_proactive_last_fired_at": fired_iso,
    }
    decision = await maybe_fire_morning_check_in(
        user_id="u1",
        timezone_name="Asia/Singapore",
        living_profile=profile,
        now_local=_at(2026, 4, 27, 7, 45),
    )
    assert decision.fired is False
    assert decision.reason == "already_fired_today"


@pytest.mark.asyncio
async def test_yesterday_fire_does_not_block_today(monkeypatch):
    """Fired at 7:30 yesterday → today's tick is fresh."""
    fired_iso = _at(2026, 4, 26, 7, 30).astimezone(timezone.utc).isoformat()
    profile = {
        "rhythm": {
            "typical_first_engage_window": "07:30-08:30",
            "typical_wake_window": "06:30-07:30",
        },
        "watch_for_tomorrow": ["principal follow-up"],
        "morning_proactive_last_fired_at": fired_iso,
    }
    # Stub out everything past the gates so we don't actually fire the brain.
    monkeypatch.setattr(
        "backend.web.proactive.triggers.morning._lookup_user_phone",
        lambda *_a, **_kw: asyncio.sleep(0, result=None),
    )
    decision = await maybe_fire_morning_check_in(
        user_id="u1",
        timezone_name="Asia/Singapore",
        living_profile=profile,
        now_local=_at(2026, 4, 27, 7, 45),
    )
    # Phone lookup returns None → no_phone reason, but the gate it
    # exposes has already passed all the earlier ones, which is what
    # this test verifies.
    assert decision.reason == "no_phone"
