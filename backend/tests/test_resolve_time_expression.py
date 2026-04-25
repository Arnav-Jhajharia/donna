"""resolve_time_expression tests — deterministic with fixed `now`."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.memory.tools.resolve_time_expression import resolve_time_expression


# 2026-04-23 (Thursday) 10:00 UTC == 18:00 Asia/Singapore.
FIXED_NOW = "2026-04-23T10:00:00+00:00"


@pytest.fixture
def patch_tz():
    with patch(
        "backend.memory.tools.resolve_time_expression._load_user_timezone",
        return_value=_coro("Asia/Singapore"),
    ):
        yield


async def _coro(value):  # helper: wrap a value as an awaitable
    return value


def _coro_fn(value):
    async def _f(*_a, **_kw):
        return value

    return _f


def _tz_patch(tz_name):
    return patch(
        "backend.memory.tools.resolve_time_expression._load_user_timezone",
        new=_coro_fn(tz_name),
    )


@pytest.mark.asyncio
async def test_now_resolves_to_now() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression("u1", expression="now", now=FIXED_NOW)
    assert res["status"] == "ok"
    assert res["payload"]["at"] == "2026-04-23T10:00:00+00:00"
    assert res["payload"]["timezone"] == "Asia/Singapore"
    # local interpretation: Thursday 18:00 SGT.
    assert res["payload"]["interpreted_as"].endswith("+08:00")


@pytest.mark.asyncio
async def test_yesterday_resolves_to_local_midnight() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression("u1", expression="yesterday", now=FIXED_NOW)
    # Yesterday midnight SGT = 2026-04-22T00:00+08:00 == 2026-04-21T16:00 UTC.
    assert res["payload"]["at"] == "2026-04-21T16:00:00+00:00"


@pytest.mark.asyncio
async def test_relative_past() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression("u1", expression="3 hours ago", now=FIXED_NOW)
    assert res["payload"]["at"] == "2026-04-23T07:00:00+00:00"


@pytest.mark.asyncio
async def test_relative_future() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression("u1", expression="in 30 minutes", now=FIXED_NOW)
    assert res["payload"]["at"] == "2026-04-23T10:30:00+00:00"


@pytest.mark.asyncio
async def test_last_weekday_picks_prior_occurrence() -> None:
    # Fixed now is Thursday 2026-04-23. "last tuesday" = 2026-04-21.
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="last tuesday", now=FIXED_NOW
        )
    # Tuesday midnight SGT = 2026-04-21T00:00+08:00 == 2026-04-20T16:00 UTC.
    assert res["payload"]["at"] == "2026-04-20T16:00:00+00:00"


@pytest.mark.asyncio
async def test_weekday_with_clock() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="last friday at 7pm", now=FIXED_NOW
        )
    # Last Friday = 2026-04-17; 19:00 SGT = 11:00 UTC.
    assert res["payload"]["at"] == "2026-04-17T11:00:00+00:00"


@pytest.mark.asyncio
async def test_next_weekday_rolls_forward() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="next monday", now=FIXED_NOW
        )
    # Next Monday after Thursday 2026-04-23 = 2026-04-27.
    assert res["payload"]["at"] == "2026-04-26T16:00:00+00:00"


@pytest.mark.asyncio
async def test_clock_today_future_stays_today() -> None:
    # 18:00 local = 10:00 UTC = now. "at 9pm" today = 21:00 SGT = 13:00 UTC.
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="at 9pm", now=FIXED_NOW
        )
    assert res["payload"]["at"] == "2026-04-23T13:00:00+00:00"


@pytest.mark.asyncio
async def test_clock_today_past_rolls_to_tomorrow() -> None:
    # "at 9am" — today 09:00 SGT has already passed (it's 18:00). Rolls.
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="at 9am", now=FIXED_NOW
        )
    # Tomorrow 09:00 SGT = 01:00 UTC.
    assert res["payload"]["at"] == "2026-04-24T01:00:00+00:00"


@pytest.mark.asyncio
async def test_unparseable_returns_degraded() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression(
            "u1", expression="a few days", now=FIXED_NOW
        )
    assert res["status"] == "degraded"
    assert "could not parse" in res["payload"]["reason"]


@pytest.mark.asyncio
async def test_empty_expression() -> None:
    with _tz_patch("Asia/Singapore"):
        res = await resolve_time_expression("u1", expression="   ", now=FIXED_NOW)
    assert res["status"] == "degraded"


@pytest.mark.asyncio
async def test_missing_timezone_falls_back_to_default() -> None:
    with _tz_patch(None):
        res = await resolve_time_expression("u1", expression="now", now=FIXED_NOW)
    assert res["status"] == "ok"
    assert res["payload"]["timezone"] == "Asia/Singapore"  # DEFAULT_TIMEZONE
