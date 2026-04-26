"""Calendar spawner: classification, dedup, end-to-end materialise."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_attention_paths(tmp_path, monkeypatch):
    """Point file-backed stores at tmp_path so tests do not pollute ~/.donna."""
    monkeypatch.setenv("DONNA_ATTENTION_STORE", str(tmp_path / "attentions.json"))
    monkeypatch.setenv("DONNA_SPAWNER_DEDUP_PATH", str(tmp_path / "dedup.json"))
    # Reload templates in case env override is in effect.
    from proactive.spawners import templates as templates_mod

    templates_mod.reload()
    yield
    templates_mod.reload()


@pytest.fixture
def _stub_haiku(monkeypatch):
    """Make the Haiku fallback explicit + deterministic for the test."""
    monkeypatch.delenv("DONNA_SPAWNER_HAIKU_FALLBACK", raising=False)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _calendar_event(
    *,
    event_id: str = "evt-1",
    summary: str = "midterm exam",
    hours_from_now: float = 20.0,
    duration_minutes: int = 120,
    attendees: list[str] | None = None,
) -> dict:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    end = start + timedelta(minutes=duration_minutes)
    event: dict = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if attendees:
        event["attendees"] = [{"email": a} for a in attendees]
    return event


# ── Classification + spawn tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exam_event_spawns_two_live_attentions(db, _stub_haiku):
    from sqlalchemy import select

    from db.models import AttentionRow, DonnaSchedule
    from proactive.spawners import calendar as calendar_spawner

    event = _calendar_event(summary="midterm exam", hours_from_now=20)
    ids = await calendar_spawner.maybe_spawn(event, "u1")

    assert len(ids) == 2, f"expected 2 spawns, got {len(ids)} ids={ids}"

    async with db() as s:
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
        schedules = (await s.execute(select(DonnaSchedule))).scalars().all()
    assert len(attentions) == 2
    assert all(a.origin == "shadow_inferred" for a in attentions)
    assert all(a.status == "live" for a in attentions)
    assert len(schedules) == 2
    for sched in schedules:
        assert sched.origin == "donna"


@pytest.mark.asyncio
async def test_routine_recurring_event_drops(db, _stub_haiku):
    from sqlalchemy import select

    from db.models import AttentionRow
    from proactive.spawners import calendar as calendar_spawner

    event = _calendar_event(summary="weekly standup", hours_from_now=4)
    ids = await calendar_spawner.maybe_spawn(event, "u1")
    assert ids == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_social_lunch_event_drops(db, _stub_haiku):
    from sqlalchemy import select

    from db.models import AttentionRow
    from proactive.spawners import calendar as calendar_spawner

    event = _calendar_event(
        summary="lunch with team",
        hours_from_now=4,
        duration_minutes=30,
    )
    ids = await calendar_spawner.maybe_spawn(event, "u1")
    assert ids == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_dedup_prevents_second_spawn(db, _stub_haiku):
    from sqlalchemy import select

    from db.models import AttentionRow
    from proactive.spawners import calendar as calendar_spawner

    event = _calendar_event(summary="midterm exam", hours_from_now=20)
    first = await calendar_spawner.maybe_spawn(event, "u1")
    assert len(first) == 2
    second = await calendar_spawner.maybe_spawn(event, "u1")
    assert second == []

    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_event_update_keeps_existing_templates(db, _stub_haiku):
    """Updating the event title without changing category replays the templates
    but the dedup ledger keys on (event_id, template_id) so no new rows land."""
    from sqlalchemy import select

    from db.models import AttentionRow
    from proactive.spawners import calendar as calendar_spawner

    first = _calendar_event(summary="midterm exam", hours_from_now=20)
    second_payload = _calendar_event(
        event_id=first["id"],
        summary="midterm exam (rescheduled)",
        hours_from_now=20,
    )
    await calendar_spawner.maybe_spawn(first, "u1")
    await calendar_spawner.maybe_spawn(second_payload, "u1")

    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(rows) == 2  # exam_wakeup + exam_prep, no doubles


@pytest.mark.asyncio
async def test_haiku_fallback_invoked_for_long_meeting(db, monkeypatch):
    """Stakes meeting (≥45min, ≥2 attendees) classifies via the deterministic
    rule even without ``DONNA_SPAWNER_HAIKU_FALLBACK``. Confidence is medium →
    SHADOW (not LIVE)."""
    from sqlalchemy import select

    from db.models import AttentionRow, DonnaSchedule
    from proactive.spawners import calendar as calendar_spawner

    called = {"n": 0}

    real_classify = calendar_spawner._classify_with_haiku

    async def _spy(event):
        called["n"] += 1
        return await real_classify(event)

    monkeypatch.setattr(calendar_spawner, "_classify_with_haiku", _spy)

    event = _calendar_event(
        summary="quarterly review",
        hours_from_now=12,
        duration_minutes=60,
        attendees=["a@x.com", "b@y.com", "c@z.com"],
    )
    ids = await calendar_spawner.maybe_spawn(event, "u1")
    assert called["n"] == 1
    assert len(ids) == 1

    async with db() as s:
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
        schedules = (await s.execute(select(DonnaSchedule))).scalars().all()
    # Stakes meeting is medium → SHADOW; AttentionRow only mirrors LIVE
    # attentions written via persist_attention. The shadow path saves
    # only to the file-backed AttentionStore, so AttentionRow stays empty.
    assert attentions == []
    assert schedules == []


@pytest.mark.asyncio
async def test_event_too_far_in_future_is_ignored(db):
    from sqlalchemy import select

    from db.models import AttentionRow
    from proactive.spawners import calendar as calendar_spawner

    event = _calendar_event(summary="midterm exam", hours_from_now=24 * 30)
    ids = await calendar_spawner.maybe_spawn(event, "u1")
    assert ids == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_calendar_ingest_calls_spawner(db, monkeypatch, _stub_haiku):
    """ingest_calendar_event hooks into the spawner without breaking on errors."""
    from sqlalchemy import select

    from backend.integrations.calendar_ingest import ingest_calendar_event
    from db.models import CalendarEntry, AttentionRow

    event = _calendar_event(summary="midterm exam", hours_from_now=20)
    await ingest_calendar_event("u1", event)

    async with db() as s:
        cals = (await s.execute(select(CalendarEntry))).scalars().all()
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(cals) == 1
    assert len(attentions) == 2


@pytest.mark.asyncio
async def test_spawner_never_raises_on_broken_event(db):
    from proactive.spawners import calendar as calendar_spawner

    # Garbage payload; spawner must swallow and return [].
    ids = await calendar_spawner.maybe_spawn({"not": "an event"}, "u1")
    assert ids == []


@pytest.mark.asyncio
async def test_sweep_upcoming_picks_up_calendar_entries(db, _stub_haiku):
    from sqlalchemy import select

    from db.models import AttentionRow, CalendarEntry
    from proactive.spawners import calendar as calendar_spawner

    start = datetime.now(timezone.utc) + timedelta(hours=20)
    async with db() as s:
        s.add(
            CalendarEntry(
                user_id="u1",
                title="midterm exam",
                start_time=start.replace(tzinfo=None),
                end_time=(start + timedelta(hours=2)).replace(tzinfo=None),
                google_event_id="sweep-1",
            )
        )
        await s.commit()

    ids = await calendar_spawner.sweep_upcoming("u1", hours=24)
    assert len(ids) == 2
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(rows) == 2
