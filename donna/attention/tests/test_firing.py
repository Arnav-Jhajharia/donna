"""Tests for the attention firing tier.

These cover the pure cadence-evaluation path. The DB-touching helpers
(``materialize_next_fire``, ``cancel_pending_fires``, ``snooze_pending_fires``,
``list_pending_for_user``) are exercised in integration tests that bring up
postgres; they are intentionally thin wrappers and not unit-testable here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from donna.attention.firing import (
    RecurrenceMeta,
    compute_next_fire,
    recurrence_meta_for,
)
from donna.attention.schema import (
    AttentionSpec,
    Cadence,
    Extractor,
    Source,
    Subject,
    SurfacePolicy,
)
from donna.attention.vocabulary import (
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
)


# -- compute_next_fire: ONE_SHOT --------------------------------------------


def test_one_shot_in_future_returns_trigger_at() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.ONE_SHOT,
        params={"trigger_at": "2026-04-26T17:00:00+00:00"},
    )

    result = compute_next_fire(cadence, after=after)

    assert result == datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc)


def test_one_shot_in_past_returns_none() -> None:
    after = datetime(2026, 4, 26, 18, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.ONE_SHOT,
        params={"trigger_at": "2026-04-26T17:00:00+00:00"},
    )

    assert compute_next_fire(cadence, after=after) is None


def test_one_shot_with_z_suffix_parses() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.ONE_SHOT,
        params={"trigger_at": "2026-04-26T17:00:00Z"},
    )

    assert compute_next_fire(cadence, after=after) == datetime(
        2026, 4, 26, 17, 0, tzinfo=timezone.utc
    )


def test_one_shot_naive_after_is_treated_as_utc() -> None:
    naive = datetime(2026, 4, 26, 12, 0)
    cadence = Cadence(
        type=CadenceType.ONE_SHOT,
        params={"trigger_at": "2026-04-26T13:00:00+00:00"},
    )

    assert compute_next_fire(cadence, after=naive) == datetime(
        2026, 4, 26, 13, 0, tzinfo=timezone.utc
    )


# -- compute_next_fire: SCHEDULED interval ----------------------------------


def test_scheduled_interval_adds_seconds() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"interval_seconds": 3600},
    )

    assert compute_next_fire(cadence, after=after) == datetime(
        2026, 4, 26, 13, 0, tzinfo=timezone.utc
    )


def test_scheduled_interval_zero_returns_none() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"interval_seconds": 0},
    )

    assert compute_next_fire(cadence, after=after) is None


# -- compute_next_fire: SCHEDULED cron --------------------------------------


def test_scheduled_cron_daily_9am_in_user_tz() -> None:
    # User is in Asia/Singapore (+08:00). Cron "0 9 * * *" should resolve to
    # 09:00 Singapore time — i.e. 01:00 UTC on the same day.
    after = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    cadence = Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * *"})

    result = compute_next_fire(cadence, after=after, tz="Asia/Singapore")

    assert result == datetime(2026, 4, 26, 1, 0, tzinfo=timezone.utc)


def test_scheduled_cron_weekdays_only() -> None:
    # 2026-04-26 is a Sunday (UTC). The next weekday-9am fire in Singapore tz
    # is Monday 2026-04-27 09:00 SGT = 2026-04-27 01:00 UTC.
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"cron": "0 9 * * 1-5"},
    )

    result = compute_next_fire(cadence, after=after, tz="Asia/Singapore")

    assert result == datetime(2026, 4, 27, 1, 0, tzinfo=timezone.utc)


def test_scheduled_cron_invalid_expression_returns_none() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"cron": "not a cron expression"},
    )

    assert compute_next_fire(cadence, after=after) is None


# -- compute_next_fire: SCHEDULED monthly_day -------------------------------


def test_monthly_day_specific_day_clamps_to_month_length() -> None:
    # Day 31 in a 30-day month should clamp to the 30th.
    after = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"monthly_day": 31, "hour": 9, "minute": 0},
    )

    result = compute_next_fire(cadence, after=after, tz="UTC")

    # June has 30 days, so the clamped fire is June 30 09:00 UTC.
    assert result == datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc)


def test_monthly_day_last_resolves_to_last_day_of_month() -> None:
    after = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"monthly_day": "last", "hour": 18, "minute": 0},
    )

    result = compute_next_fire(cadence, after=after, tz="UTC")

    # Feb 2026 has 28 days.
    assert result == datetime(2026, 2, 28, 18, 0, tzinfo=timezone.utc)


def test_monthly_day_when_today_already_passed_rolls_to_next_month() -> None:
    # On the 5th of a month asking for monthly_day=5 with hour already past
    # should land on the 5th of the following month.
    after = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.SCHEDULED,
        params={"monthly_day": 5, "hour": 9, "minute": 0},
    )

    result = compute_next_fire(cadence, after=after, tz="UTC")

    assert result == datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)


# -- compute_next_fire: unsupported cadence types ---------------------------


def test_on_event_returns_none() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(
        type=CadenceType.ON_EVENT,
        params={"event_source": "calendar_events", "lead_minutes": 60},
    )

    assert compute_next_fire(cadence, after=after) is None


def test_on_demand_returns_none() -> None:
    after = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    cadence = Cadence(type=CadenceType.ON_DEMAND, params={})

    assert compute_next_fire(cadence, after=after) is None


# -- RecurrenceMeta round-trip ----------------------------------------------


def _ping_spec(question: str, cadence: Cadence) -> AttentionSpec:
    return AttentionSpec(
        title="test reminder",
        description="unit test ping",
        card=CardType.PING,
        subject=Subject(name="self", type=SubjectType.SELF),
        domain_tags=[DomainTag.REMINDER],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": question, "expected_shape": "text"},
            )
        ],
        extractor=Extractor(prompt="echo the elicitation question back"),
        cadence=cadence,
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
    )


def test_recurrence_meta_extracts_cadence_and_question() -> None:
    spec = _ping_spec(
        "call mom",
        Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * *"}),
    )

    meta = recurrence_meta_for(spec, user_tz="Asia/Singapore")

    assert meta.question == "call mom"
    assert meta.cadence_type == "scheduled"
    assert meta.cadence_params == {"cron": "0 9 * * *"}
    assert meta.user_tz == "Asia/Singapore"
    assert meta.is_recurring is True


def test_recurrence_meta_one_shot_is_not_recurring() -> None:
    spec = _ping_spec(
        "drink water",
        Cadence(
            type=CadenceType.ONE_SHOT,
            params={"trigger_at": "2026-04-26T17:00:00+00:00"},
        ),
    )

    meta = recurrence_meta_for(spec, user_tz="UTC")

    assert meta.is_recurring is False


def test_recurrence_meta_jsonb_round_trip() -> None:
    original = RecurrenceMeta(
        cadence_type="scheduled",
        cadence_params={"cron": "0 9 * * 1-5"},
        user_tz="Asia/Singapore",
        question="weekday journal",
    )

    restored = RecurrenceMeta.from_jsonb(original.as_jsonb())

    assert restored == original


def test_recurrence_meta_from_jsonb_rejects_garbage() -> None:
    assert RecurrenceMeta.from_jsonb(None) is None
    assert RecurrenceMeta.from_jsonb({"missing": "fields"}) is None
    assert RecurrenceMeta.from_jsonb("not a dict") is None


def test_recurrence_meta_to_cadence_validates() -> None:
    meta = RecurrenceMeta(
        cadence_type="scheduled",
        cadence_params={"cron": "0 9 * * *"},
        user_tz="UTC",
        question="x",
    )

    cadence = meta.to_cadence()

    assert cadence.type is CadenceType.SCHEDULED
    assert cadence.params == {"cron": "0 9 * * *"}
