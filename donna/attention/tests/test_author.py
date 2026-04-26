"""Author tests: ping short-circuit + fallback + LLM path mocked."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from datetime import datetime
from zoneinfo import ZoneInfo

from donna.attention.author import (
    ReminderInPastError,
    UnparseableReminderError,
    _looks_like_bare_reminder,
    _parse_reminder,
    _ping_spec,
    author_spec,
)
from donna.attention.normalize import NormalizedIntent, NormalizedSignals, UserContext
from donna.attention.retrieve import retrieve_top_k
from donna.attention.schema import AttentionSpec
from donna.attention.vocabulary import CadenceType, CardType, SourceType


def _normalized(raw: str) -> NormalizedIntent:
    return NormalizedIntent(
        raw_text=raw,
        normalized_text=raw,
        signals=NormalizedSignals(subject_name="thing"),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("remind me to call mom at 6pm", True),
        ("ping me in the morning", True),
        ("don't let me forget groceries", True),
        ("keep an eye on Poke", False),
        ("track my subscriptions", False),
    ],
)
def test_looks_like_bare_reminder(raw, expected):
    assert _looks_like_bare_reminder(raw) is expected


@pytest.mark.unit
def test_ping_spec_validates():
    spec = _ping_spec("remind me to call mom at 6pm", _normalized("remind me to call mom at 6pm"))
    assert isinstance(spec, AttentionSpec)
    assert spec.card is CardType.PING
    assert spec.sources[0].type is SourceType.USER_ELICITATION


@pytest.mark.unit
def test_author_ping_shortcircuit(monkeypatch):
    # Ensure the LLM path is NOT called for bare reminders
    async def fail(**kwargs):
        raise AssertionError("LLM should not be called for ping short-circuit")

    monkeypatch.setattr(
        "backend.memory.retrieval.structured.call_structured", fail
    )
    norm = _normalized("remind me to call mom at 6pm")
    result = asyncio.run(author_spec(norm, UserContext(user_id="u1")))
    assert result.via == "ping_shortcircuit"
    assert result.spec.card is CardType.PING


@pytest.mark.unit
def test_author_falls_back_when_llm_returns_none(monkeypatch):
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )
    norm = _normalized("keep an eye on Poke")
    result = asyncio.run(author_spec(norm, UserContext(user_id="u1")))
    assert result.via == "fallback"
    assert result.spec.title


@pytest.mark.unit
def test_retrieved_passed_through(monkeypatch):
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )
    hits = retrieve_top_k("keep an eye on Poke", k=3)
    norm = _normalized("keep an eye on Poke")
    result = asyncio.run(
        author_spec(norm, UserContext(user_id="u1"), retrieved=hits)
    )
    assert result.retrieved_ids == tuple(h.example.example_id for h in hits)


# -- _parse_reminder: monthly-day edge cases (issue #3) ---------------------


@pytest.mark.unit
def test_parse_reminder_day_5_stays_cron():
    """Days 1..28 keep the cron shape (unchanged behavior)."""
    cadence = _parse_reminder("pay mcst on the 5th of every month at 9am", "Asia/Singapore")
    assert cadence.type is CadenceType.SCHEDULED
    assert cadence.params.get("cron") == "0 9 5 * *"
    assert "monthly_day" not in cadence.params


@pytest.mark.unit
@pytest.mark.parametrize("day", [29, 30, 31])
def test_parse_reminder_day_29_to_31_uses_monthly_day(day):
    """Days 29..31 must use monthly_day shape so short months clamp to last."""
    raw = f"remind me on the {day}th of every month at 9am"
    cadence = _parse_reminder(raw, "Asia/Singapore")
    assert cadence.type is CadenceType.SCHEDULED
    assert cadence.params["monthly_day"] == day
    assert cadence.params["hour"] == 9
    assert cadence.params["minute"] == 0
    assert "cron" not in cadence.params


@pytest.mark.unit
def test_parse_reminder_last_of_month():
    cadence = _parse_reminder(
        "pay rent on the last of every month at 9am", "Asia/Singapore"
    )
    assert cadence.type is CadenceType.SCHEDULED
    assert cadence.params["monthly_day"] == "last"
    assert cadence.params["hour"] == 9


@pytest.mark.unit
def test_parse_reminder_last_day_variant():
    cadence = _parse_reminder(
        "remind me the last day of every month at 6pm", "Asia/Singapore"
    )
    assert cadence.type is CadenceType.SCHEDULED
    assert cadence.params["monthly_day"] == "last"
    assert cadence.params["hour"] == 18


# -- _parse_reminder: same-day "today" handling (issue #4) -------------------


@pytest.mark.unit
def test_parse_reminder_today_explicit_past_raises():
    """'remind me today at 8am' when it's already 9am must NOT silently roll to tomorrow."""
    tz = ZoneInfo("Asia/Singapore")
    now = datetime(2026, 4, 24, 9, 0, tzinfo=tz)
    with pytest.raises(ReminderInPastError):
        _parse_reminder("remind me today at 8am", "Asia/Singapore", now=now)


@pytest.mark.unit
def test_parse_reminder_today_explicit_future_ok():
    """'remind me today at 6pm' at 3pm stays same-day."""
    tz = ZoneInfo("Asia/Singapore")
    now = datetime(2026, 4, 24, 15, 0, tzinfo=tz)
    cadence = _parse_reminder("remind me today at 6pm", "Asia/Singapore", now=now)
    assert cadence.type is CadenceType.ONE_SHOT
    trigger = datetime.fromisoformat(cadence.params["trigger_at"])
    assert trigger.astimezone(tz).date() == now.date()
    assert trigger.astimezone(tz).hour == 18


@pytest.mark.unit
def test_parse_reminder_no_token_past_rolls_to_tomorrow():
    """Regression: with no day-token, past times still roll to tomorrow (pragmatic default)."""
    tz = ZoneInfo("Asia/Singapore")
    now = datetime(2026, 4, 24, 9, 0, tzinfo=tz)
    cadence = _parse_reminder("remind me at 8am", "Asia/Singapore", now=now)
    trigger = datetime.fromisoformat(cadence.params["trigger_at"])
    assert (trigger.astimezone(tz).date() - now.date()).days == 1
    assert trigger.astimezone(tz).hour == 8


@pytest.mark.unit
def test_parse_reminder_tomorrow_explicit_adds_a_day():
    tz = ZoneInfo("Asia/Singapore")
    now = datetime(2026, 4, 24, 15, 0, tzinfo=tz)
    cadence = _parse_reminder(
        "remind me tomorrow at 9am", "Asia/Singapore", now=now
    )
    trigger = datetime.fromisoformat(cadence.params["trigger_at"])
    assert (trigger.astimezone(tz).date() - now.date()).days == 1


# -- _parse_reminder: unparseable fallback (issue #5) ------------------------


@pytest.mark.unit
def test_parse_reminder_no_time_raises():
    """'remind me to call mom' has no time/recurrence — must refuse to invent one."""
    tz = ZoneInfo("Asia/Singapore")
    now = datetime(2026, 4, 24, 10, 0, tzinfo=tz)
    with pytest.raises(UnparseableReminderError):
        _parse_reminder("remind me to call mom", "Asia/Singapore", now=now)


@pytest.mark.unit
def test_author_ping_shortcircuit_falls_through_on_unparseable(monkeypatch):
    """When the reminder has no time info, ping short-circuit must fall through to LLM."""
    async def fake_none(**kwargs):
        return None

    monkeypatch.setattr(
        "donna.attention.author._call_with_validation_retry", fake_none
    )
    norm = _normalized("remind me to call mom")
    # No time info → UnparseableReminderError inside _parse_reminder →
    # ping short-circuit skipped → LLM path → fallback-from-retrieval.
    result = asyncio.run(author_spec(norm, UserContext(user_id="u1")))
    assert result.via != "ping_shortcircuit"
