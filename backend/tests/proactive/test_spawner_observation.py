"""Observation spawner: drinking, sleep regression, mood, dedup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_attention_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DONNA_ATTENTION_STORE", str(tmp_path / "attentions.json"))
    monkeypatch.setenv("DONNA_SPAWNER_DEDUP_PATH", str(tmp_path / "dedup.json"))
    from proactive.spawners import templates as templates_mod

    templates_mod.reload()
    yield
    templates_mod.reload()


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _seed_donna_instance(db, *, user_id: str = "u1", obs_type: str) -> str:
    """Mirror the log_observation upsert side-effect."""
    from db.models import DonnaInstance

    instance_id = uuid4().hex
    async with db() as s:
        s.add(
            DonnaInstance(
                id=instance_id,
                user_id=user_id,
                primitive="track",
                connector="whatsapp_manual",
                label=obs_type,
                config={"type": obs_type},
                status="active",
            )
        )
        await s.commit()
    return instance_id


async def _insert_observation(
    db,
    *,
    user_id: str = "u1",
    obs_type: str,
    fields: dict,
    event_time_utc: datetime,
    raw: str = "",
) -> str:
    from db.models import Observation

    instance_id = await _seed_donna_instance(db, user_id=user_id, obs_type=obs_type)
    obs_id = uuid4().hex
    async with db() as s:
        obs = Observation(
            id=obs_id,
            user_id=user_id,
            instance_id=instance_id,
            type=obs_type,
            fields=fields,
            tags={},
            raw=raw,
            event_time=event_time_utc.replace(tzinfo=None),
            confidence=1.0,
        )
        s.add(obs)
        await s.commit()
    return obs_id


# ── Drinking event ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drinking_event_evening_spawns_one_high_attention(db, monkeypatch):
    from sqlalchemy import select

    from db.models import AttentionRow, DonnaSchedule, Observation
    from proactive.spawners import observation as observation_spawner

    # Force the evening-window check to True. The window is wall-clock
    # dependent in real life; we want the assertion to be deterministic.
    monkeypatch.setattr(observation_spawner, "_is_evening", lambda *_a, **_kw: True)

    event_time = datetime.now(timezone.utc) - timedelta(hours=8)
    obs_id = await _insert_observation(
        db,
        obs_type="drinking_event",
        fields={"drinks": 5},
        event_time_utc=event_time,
        raw="rough night",
    )
    async with db() as s:
        obs_row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()
    ids = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert len(ids) == 1, f"expected 1 spawn, got {ids}"

    async with db() as s:
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
        schedules = (await s.execute(select(DonnaSchedule))).scalars().all()
    assert len(attentions) == 1
    assert attentions[0].status == "live"
    assert len(schedules) == 1


@pytest.mark.asyncio
async def test_drinking_dedup_prevents_double_spawn(db, monkeypatch):
    """Force the evening-window check to True so the first spawn always fires.

    Then confirm the second call is a no-op via the dedup ledger.
    """
    from sqlalchemy import select

    from db.models import AttentionRow, Observation
    from proactive.spawners import observation as observation_spawner

    monkeypatch.setattr(observation_spawner, "_is_evening", lambda *_a, **_kw: True)

    event_time = datetime.now(timezone.utc) - timedelta(hours=2)
    obs_id = await _insert_observation(
        db,
        obs_type="drinking_event",
        fields={"drinks": 5},
        event_time_utc=event_time,
        raw="rough night",
    )
    async with db() as s:
        obs_row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()

    first = await observation_spawner.maybe_spawn(obs_row, "u1")
    second = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert len(first) == 1
    assert second == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(rows) == 1


# ── Sleep regression ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_regression_after_three_short_nights(db, monkeypatch):
    """2 prior <6h nights + a 3rd live <6h obs → spawn one HIGH attention."""
    from sqlalchemy import select

    from db.models import AttentionRow, Observation, User
    from proactive.spawners import observation as observation_spawner

    # Seed user with a known sleep_time so the resolver picks 22:00.
    async with db() as s:
        user = (
            await s.execute(select(User).where(User.id == "u1"))
        ).scalar_one()
        user.sleep_time = "22:00"
        await s.commit()

    # Two prior short nights.
    base = datetime.now(timezone.utc) - timedelta(days=2)
    for offset_h in (0, 24):
        await _insert_observation(
            db,
            obs_type="sleep",
            fields={"hours": 5.0},
            event_time_utc=base + timedelta(hours=offset_h),
            raw="bad sleep",
        )

    # Third short night → the live trigger.
    triggering_id = await _insert_observation(
        db,
        obs_type="sleep",
        fields={"hours": 4.5},
        event_time_utc=datetime.now(timezone.utc) - timedelta(minutes=30),
        raw="another bad night",
    )
    async with db() as s:
        obs_row = (
            await s.execute(
                select(Observation).where(Observation.id == triggering_id)
            )
        ).scalar_one()

    ids = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert len(ids) == 1, f"expected 1 spawn, got {ids}"

    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "live"


@pytest.mark.asyncio
async def test_sleep_obs_with_only_one_short_night_does_not_spawn(db):
    from sqlalchemy import select

    from db.models import AttentionRow, Observation
    from proactive.spawners import observation as observation_spawner

    obs_id = await _insert_observation(
        db,
        obs_type="sleep",
        fields={"hours": 5.0},
        event_time_utc=datetime.now(timezone.utc) - timedelta(minutes=10),
        raw="single short night",
    )
    async with db() as s:
        obs_row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()

    ids = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert ids == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert rows == []


# ── Mood low ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mood_low_spawns_shadow_not_live(db):
    """MEDIUM confidence template lands SHADOW (file store), no AttentionRow."""
    from sqlalchemy import select

    from db.models import AttentionRow, Observation
    from donna.attention.schema import AttentionStatus
    from donna.attention.store import AttentionStore
    from proactive.spawners import observation as observation_spawner

    obs_id = await _insert_observation(
        db,
        obs_type="mood",
        fields={"score": "low"},
        event_time_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
        raw="feel low today",
    )
    async with db() as s:
        obs_row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()

    ids = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert len(ids) == 1
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    # SHADOW path does not write to the postgres mirror.
    assert rows == []

    # File store should now hold the SHADOW row.
    store = AttentionStore()
    shadows = store.list(status=AttentionStatus.SHADOW)
    assert len(shadows) == 1


# ── Skipped meal ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skipped_meal_observation_drops(db):
    from sqlalchemy import select

    from db.models import AttentionRow, Observation
    from proactive.spawners import observation as observation_spawner

    obs_id = await _insert_observation(
        db,
        obs_type="meal",
        fields={"ate": False, "skipped": True},
        event_time_utc=datetime.now(timezone.utc) - timedelta(minutes=10),
        raw="skipped lunch",
    )
    async with db() as s:
        obs_row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()
    ids = await observation_spawner.maybe_spawn(obs_row, "u1")
    assert ids == []
    async with db() as s:
        rows = (await s.execute(select(AttentionRow))).scalars().all()
    assert rows == []


# ── Resilience ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spawner_never_raises_on_garbage(db):
    from proactive.spawners import observation as observation_spawner

    # observation=None should noop.
    assert await observation_spawner.maybe_spawn(None, "u1") == []
    # observation missing required fields should noop.
    assert await observation_spawner.maybe_spawn({"id": None}, "u1") == []
