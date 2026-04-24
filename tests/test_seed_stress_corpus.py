"""Tests for the memory stress-test seed corpus.

Exercises the pure data generators (no DB). The async writer path is not
unit-tested here — it's idempotent and hits real Postgres, which belongs
in integration.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from scripts._seed_corpus.anchor import resolve_anchor
from scripts._seed_corpus.briefs import build_brief_variants
from scripts._seed_corpus.calendar import build_calendar_rows
from scripts._seed_corpus.chat import build_chat_rows
from scripts._seed_corpus.observations import build_observation_rows
from scripts._seed_corpus.open_loops import build_open_loop_rows
from scripts._seed_corpus.profile import (
    CURRENT_TIMEZONE,
    HOME_TIMEZONE,
    SEED_USER_ID,
    TRIP_TIMEZONE,
    build_profile_row,
    timezone_for_offset,
)


ANCHOR = datetime(2026, 4, 25, 0, 0, 0)


class TestAnchor:
    def test_resolve_anchor_default_is_utc_naive(self) -> None:
        window = resolve_anchor(None)
        assert window.anchor.tzinfo is None
        assert window.start < window.anchor < window.end

    def test_resolve_anchor_parses_iso_string(self) -> None:
        window = resolve_anchor("2026-04-25T00:00:00")
        assert window.anchor == datetime(2026, 4, 25, 0, 0, 0)

    def test_resolve_anchor_converts_aware_to_utc_naive(self) -> None:
        window = resolve_anchor("2026-04-25T08:00:00+08:00")
        assert window.anchor == datetime(2026, 4, 25, 0, 0, 0)


class TestProfile:
    def test_profile_row_shape(self) -> None:
        row = build_profile_row(ANCHOR)
        assert row.id == SEED_USER_ID
        assert row.timezone == CURRENT_TIMEZONE
        assert row.is_sandbox is True
        assert row.onboarding_goals == {"tz_done": True, "watch_done": True}
        for key in ("preferred_name", "current_city", "home_city", "current_timezone", "profession"):
            assert key in row.facts
            assert row.facts[key]["value"]

    def test_timezone_for_offset_ny_trip(self) -> None:
        assert timezone_for_offset(-20) == CURRENT_TIMEZONE
        assert timezone_for_offset(-15) == TRIP_TIMEZONE
        assert timezone_for_offset(-13) == TRIP_TIMEZONE
        assert timezone_for_offset(-10) == CURRENT_TIMEZONE
        # Home TZ is a reference only; Kai's "current" tz reflects where he is.
        assert HOME_TIMEZONE != CURRENT_TIMEZONE


class TestChat:
    def test_chat_row_count_and_order(self) -> None:
        rng = random.Random(42)
        rows = build_chat_rows(SEED_USER_ID, ANCHOR, rng, total=200)
        assert len(rows) == 200
        assert all(r.user_id == SEED_USER_ID for r in rows)
        timestamps = [r.created_at for r in rows]
        assert timestamps == sorted(timestamps), "chat rows must be ascending by time"

    def test_chat_is_deterministic_for_same_seed(self) -> None:
        a = build_chat_rows(SEED_USER_ID, ANCHOR, random.Random(42), total=200)
        b = build_chat_rows(SEED_USER_ID, ANCHOR, random.Random(42), total=200)
        assert [(r.role, r.content, r.created_at) for r in a] == [
            (r.role, r.content, r.created_at) for r in b
        ]

    def test_chat_mentions_key_people_and_companies(self) -> None:
        rng = random.Random(42)
        rows = build_chat_rows(SEED_USER_ID, ANCHOR, rng, total=200)
        joined = "\n".join(r.content for r in rows).lower()
        for mention in ("maya", "saurabh", "priya", "ravi", "stripe", "toronto", "ny"):
            assert mention in joined, f"expected {mention!r} in chat corpus"

    def test_chat_has_proactive_messages(self) -> None:
        rng = random.Random(42)
        rows = build_chat_rows(SEED_USER_ID, ANCHOR, rng, total=200)
        proactive = [r for r in rows if r.is_proactive]
        assert proactive, "expected at least one proactive donna message"
        assert all(r.role == "assistant" for r in proactive)


class TestObservations:
    def test_observation_counts_per_type(self) -> None:
        rng = random.Random(42)
        rows = build_observation_rows(SEED_USER_ID, ANCHOR, rng)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.type] = counts.get(r.type, 0) + 1
        assert counts == {"expense": 25, "meal": 18, "mood": 7, "sleep": 6, "habit": 4}

    def test_observations_ordered_and_within_window(self) -> None:
        rng = random.Random(42)
        rows = build_observation_rows(SEED_USER_ID, ANCHOR, rng)
        times = [r.event_time for r in rows]
        assert times == sorted(times)
        window_start = ANCHOR - timedelta(days=30)
        window_end = ANCHOR + timedelta(days=1)
        assert all(window_start <= t <= window_end for t in times)

    def test_ny_trip_expenses_use_usd(self) -> None:
        rng = random.Random(42)
        rows = build_observation_rows(SEED_USER_ID, ANCHOR, rng)
        trip_start = ANCHOR - timedelta(days=15)
        trip_end = ANCHOR - timedelta(days=13)
        for row in rows:
            if row.type != "expense":
                continue
            if trip_start <= row.event_time <= trip_end:
                assert row.fields["currency"] == "USD"


class TestOpenLoops:
    def test_open_loop_count_and_one_resolved(self) -> None:
        rows = build_open_loop_rows(SEED_USER_ID, ANCHOR)
        assert len(rows) == 8
        resolved = [r for r in rows if r.status == "resolved"]
        assert len(resolved) == 1
        assert resolved[0].resolved_at is not None

    def test_open_loops_have_varied_ages(self) -> None:
        rows = build_open_loop_rows(SEED_USER_ID, ANCHOR)
        ages = [(ANCHOR - r.created_at).days for r in rows]
        assert min(ages) <= 2, "expected a fresh loop"
        assert max(ages) >= 14, "expected a stale loop"


class TestCalendar:
    def test_calendar_has_past_and_upcoming(self) -> None:
        rows = build_calendar_rows(SEED_USER_ID, ANCHOR)
        past = [r for r in rows if r.start_time < ANCHOR]
        upcoming = [r for r in rows if r.start_time >= ANCHOR]
        assert past, "expected past events"
        assert upcoming, "expected upcoming events"
        assert len(rows) >= 15

    def test_calendar_includes_weekly_recurring_one_on_one(self) -> None:
        rows = build_calendar_rows(SEED_USER_ID, ANCHOR)
        titles = [r.title for r in rows]
        assert titles.count("1:1 with maya") >= 2
        assert any(r.title == "flight SIN-YYZ" for r in rows)


class TestBriefs:
    def test_three_freshness_variants(self) -> None:
        variants = build_brief_variants(ANCHOR)
        names = [v.name for v in variants]
        assert names == ["fresh", "3d_stale", "14d_stale"]
        hours = [v.staleness_hours for v in variants]
        assert hours == [0, 72, 336]

    def test_brief_payload_matches_temporal_brief_shape(self) -> None:
        variant = build_brief_variants(ANCHOR)[0]
        required_keys = {
            "implementation",
            "generated_at",
            "summary",
            "current_status",
            "last_week",
            "this_week",
            "next_week",
            "open_loops",
            "stale_or_uncertain",
            "evidence_used",
        }
        assert required_keys.issubset(variant.payload.keys())
        assert variant.payload["implementation"] == "windowed_timeline"


@pytest.mark.asyncio
async def test_run_dry_run_returns_plan_without_db_access(monkeypatch) -> None:
    """The dry-run path should never touch the DB."""
    from scripts import seed_stress_corpus

    async def boom(**_kwargs):
        raise AssertionError("_write_all must not be called during dry-run")

    monkeypatch.setattr(seed_stress_corpus, "_write_all", boom)

    args = _fake_args(dry_run=True, anchor="2026-04-25T00:00:00", brief="fresh", seed=42)
    plan = await seed_stress_corpus._run(args)

    assert plan.anchor.anchor == ANCHOR
    assert plan.brief.name == "fresh"
    assert plan.chat_count == 200
    assert plan.observation_count == 60
    assert plan.open_loop_count == 8
    assert plan.calendar_count >= 15


def _fake_args(**kwargs):
    class _Ns:
        pass

    ns = _Ns()
    for key, value in kwargs.items():
        setattr(ns, key, value)
    ns.verbose = kwargs.get("verbose", False)
    return ns
