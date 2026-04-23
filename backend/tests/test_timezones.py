from __future__ import annotations

from datetime import datetime, timezone

from backend.memory.time import (
    coerce_to_utc_naive,
    format_local,
    local_day_bounds,
    local_week_bounds,
)


def test_naive_model_time_is_interpreted_in_user_timezone():
    dt = coerce_to_utc_naive("2026-04-21T10:30:00", "Asia/Singapore")

    assert dt.isoformat() == "2026-04-21T02:30:00"


def test_offset_aware_model_time_is_respected():
    dt = coerce_to_utc_naive("2026-04-21T10:30:00+08:00", "America/New_York")

    assert dt.isoformat() == "2026-04-21T02:30:00"


def test_local_day_bounds_handle_dst_start():
    now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    start, end = local_day_bounds(now, "America/New_York")

    assert start.isoformat() == "2026-03-08T05:00:00"
    assert end.isoformat() == "2026-03-09T04:00:00"


def test_local_week_bounds_use_user_week_boundary():
    now = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    start, end = local_week_bounds(now, "Asia/Singapore")

    assert start.isoformat() == "2026-04-19T16:00:00"
    assert end.isoformat() == "2026-04-26T16:00:00"


def test_period_bounds_accept_human_spacing():
    from backend.memory.time import period_bounds

    now = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    spaced = period_bounds("last week", "Asia/Singapore", now=now)
    underscored = period_bounds("last_week", "Asia/Singapore", now=now)

    assert spaced == underscored


def test_format_local_renders_user_wall_clock():
    rendered = format_local(
        datetime(2026, 4, 21, 2, 30),
        "Asia/Singapore",
    )

    assert rendered == "2026-04-21 10:30 Asia/Singapore"


def test_format_local_falls_back_to_canonical_default_label():
    rendered = format_local(
        datetime(2026, 4, 21, 2, 30),
        "Not/AZone",
    )

    assert rendered == "2026-04-21 10:30 Asia/Singapore"
