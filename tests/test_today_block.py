"""Tests for the TODAY block (Phase 0 Task 4, memory-stress-test-plan).

The TODAY block pre-computes next-24h calendar, today's observations, active
open loops, and active attentions into the prompt so the model doesn't have
to tool-call for routine "what's on today" / "what am i forgetting" turns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from donna_runtime.context_builder import (
    TodayBlockSnapshot,
    load_today_block,
    render_today_block,
    render_turn_context,
)


def _fake_calendar_row(
    *, title: str, start_time: datetime, end_time: datetime | None = None, location: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id="cal-x",
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=location,
    )


def _fake_observation_row(
    *, type: str, event_time: datetime, fields: dict | None = None, raw: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id="obs-x",
        type=type,
        event_time=event_time,
        fields=fields or {},
        tags=[],
        raw=raw,
    )


def _fake_open_loop_row(*, content: str, created_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id="loop-x",
        content=content,
        status="active",
        created_at=created_at,
    )


def _fake_attention(*, title: str, subject_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="att-x",
        spec=SimpleNamespace(title=title, subject=SimpleNamespace(name=subject_name)),
    )


class TestRenderTodayBlock:
    """Pure render tests — no DB, no IO."""

    def test_render_empty_snapshot_returns_empty_string(self) -> None:
        snapshot = TodayBlockSnapshot(
            timezone_name="Asia/Singapore",
            local_time="2026-04-25 14:30",
            calendar=(),
            observations=(),
            open_loops=(),
            attentions=(),
        )
        assert render_today_block(snapshot) == ""

    def test_render_includes_each_populated_section(self) -> None:
        now_utc = datetime(2026, 4, 25, 6, 30)  # 14:30 SG local
        snapshot = TodayBlockSnapshot(
            timezone_name="Asia/Singapore",
            local_time="2026-04-25 14:30",
            calendar=(
                _fake_calendar_row(
                    title="board sync",
                    start_time=now_utc + timedelta(hours=1),
                    location="office",
                ),
            ),
            observations=(
                _fake_observation_row(
                    type="expense",
                    event_time=now_utc - timedelta(hours=2),
                    fields={"amount": 12, "currency": "SGD", "merchant": "coffee"},
                ),
            ),
            open_loops=(
                _fake_open_loop_row(
                    content="respond to saurabh term sheet",
                    created_at=now_utc - timedelta(days=7),
                ),
            ),
            attentions=(
                _fake_attention(title="watch india gst filing deadline", subject_name="GST quarterly"),
            ),
        )
        out = render_today_block(snapshot)
        assert out.startswith("## TODAY")
        assert "timezone: Asia/Singapore" in out
        assert "local_time: 2026-04-25 14:30" in out
        assert "next 24h" in out
        assert "board sync" in out
        assert "today's observations" in out
        assert "expense" in out
        assert "open loops" in out
        assert "saurabh" in out
        assert "attentions" in out
        assert "gst filing" in out

    def test_render_skips_sections_that_are_empty(self) -> None:
        now_utc = datetime(2026, 4, 25, 6, 30)
        snapshot = TodayBlockSnapshot(
            timezone_name="Asia/Singapore",
            local_time="2026-04-25 14:30",
            calendar=(),
            observations=(),
            open_loops=(
                _fake_open_loop_row(
                    content="follow up with maya",
                    created_at=now_utc - timedelta(days=2),
                ),
            ),
            attentions=(),
        )
        out = render_today_block(snapshot)
        assert "## TODAY" in out
        assert "open loops" in out
        assert "next 24h" not in out
        assert "today's observations" not in out
        assert "attentions" not in out

    def test_render_caps_each_section(self) -> None:
        now_utc = datetime(2026, 4, 25, 6, 30)
        many_loops = tuple(
            _fake_open_loop_row(content=f"loop {i}", created_at=now_utc - timedelta(days=i))
            for i in range(20)
        )
        snapshot = TodayBlockSnapshot(
            timezone_name="Asia/Singapore",
            local_time="2026-04-25 14:30",
            calendar=(),
            observations=(),
            open_loops=many_loops,
            attentions=(),
        )
        out = render_today_block(snapshot)
        # Caps at ~6 loops.
        assert out.count("loop ") <= 8  # includes header word "loops"


class TestLoadTodayBlock:
    """Orchestration test — DB fetchers monkeypatched."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_user_id(self) -> None:
        assert await load_today_block(None) == ""

    @pytest.mark.asyncio
    async def test_composes_sections_from_fetchers(self) -> None:
        now_utc = datetime(2026, 4, 25, 6, 30, tzinfo=timezone.utc).replace(tzinfo=None)

        async def fake_fetch(user_id, now, timezone_name):
            assert user_id == "u-1"
            return {
                "timezone_name": "Asia/Singapore",
                "calendar": [
                    _fake_calendar_row(
                        title="team sync",
                        start_time=now_utc + timedelta(hours=2),
                    )
                ],
                "observations": [
                    _fake_observation_row(
                        type="meal",
                        event_time=now_utc - timedelta(hours=3),
                        fields={"meal": "lunch"},
                    )
                ],
                "open_loops": [
                    _fake_open_loop_row(
                        content="confirm dinner",
                        created_at=now_utc - timedelta(days=1),
                    )
                ],
                "attentions": [
                    _fake_attention(title="watch fundraising", subject_name="round A"),
                ],
            }

        with patch("donna_runtime.context_builder._fetch_today_sections", fake_fetch):
            out = await load_today_block("u-1", injected_now=now_utc.isoformat())

        assert "## TODAY" in out
        assert "team sync" in out
        assert "meal" in out
        assert "confirm dinner" in out
        assert "watch fundraising" in out

    @pytest.mark.asyncio
    async def test_returns_empty_on_fetch_exception(self) -> None:
        async def boom(user_id, now, timezone_name):
            raise RuntimeError("db down")

        with patch("donna_runtime.context_builder._fetch_today_sections", boom):
            out = await load_today_block("u-1")

        assert out == ""


class TestRenderTurnContextIncludesTodayBlock:
    """Integration: render_turn_context should include the TODAY block when
    fetchers return data, and omit the section when they don't."""

    @pytest.mark.asyncio
    async def test_today_block_appears_in_render_turn_context(self) -> None:
        async def fake_today(user_id, injected_now=None):
            return "## TODAY\ntimezone: Asia/Singapore, local_time: 2026-04-25 14:30\n\nopen loops (1):\n- [1d] confirm dinner"

        state = {
            "user_id": "u-1",
            "_user_name": "Arnav",
            "_user_timezone": "Asia/Singapore",
            "_tz_done": True,
            "_is_first_message": False,
        }

        with patch("donna_runtime.context_builder.load_today_block", fake_today):
            rendered = await render_turn_context(state)

        assert "## TODAY" in rendered
        assert "confirm dinner" in rendered

    @pytest.mark.asyncio
    async def test_today_block_absent_when_loader_returns_empty(self) -> None:
        async def fake_today(user_id, injected_now=None):
            return ""

        state = {
            "user_id": "u-1",
            "_user_name": "Arnav",
            "_user_timezone": "Asia/Singapore",
            "_tz_done": True,
            "_is_first_message": False,
        }

        with patch("donna_runtime.context_builder.load_today_block", fake_today):
            rendered = await render_turn_context(state)

        assert "## TODAY" not in rendered
