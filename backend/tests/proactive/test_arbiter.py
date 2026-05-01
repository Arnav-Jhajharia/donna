"""Unified arbiter extensions: topic dedup, active-chat, quiet-hours fallback."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.integrations.proactive_rate_limit import (
    can_fire_proactive,
    record_ping,
)
from db.models import ChatMessage, ProactivePing


@pytest.fixture
def _no_quiet_hours(monkeypatch):
    async def _none(_user_id):  # noqa: ANN001
        return (None, None)

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _none,
    )
    # Also clear timezone fallback so quiet hours don't fire.
    async def _no_tz(_user_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_timezone",
        _no_tz,
    )


@pytest.mark.asyncio
async def test_topic_cooldown_blocks_repeat(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 12, 0)
    await record_ping(
        "u1", source="email", message_ref="m1", at=base, topic_key="thread-A"
    )
    decision = await can_fire_proactive(
        "u1",
        source="email",
        topic_key="thread-A",
        now=base + timedelta(minutes=5),
    )
    assert decision.allowed is False
    assert "topic_cooldown" in decision.reason


@pytest.mark.asyncio
async def test_topic_cooldown_does_not_block_other_topics(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 12, 0)
    await record_ping(
        "u1", source="email", message_ref="m1", at=base, topic_key="thread-A"
    )
    decision = await can_fire_proactive(
        "u1",
        source="email",
        topic_key="thread-B",
        now=base + timedelta(minutes=40),
    )
    # global cooldown is 30 min so 40 min is past it. topic-B has no
    # prior fire so topic cooldown is also clear.
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_active_chat_blocks_recent_user_message(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 12, 0)
    async with db() as s:
        s.add(
            ChatMessage(
                user_id="u1",
                role="user",
                content="hey",
                created_at=base - timedelta(seconds=60),
            )
        )
        await s.commit()
    decision = await can_fire_proactive("u1", source="email", now=base)
    assert decision.allowed is False
    assert "active_chat" in decision.reason


@pytest.mark.asyncio
async def test_active_chat_clear_after_window(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 12, 0)
    async with db() as s:
        s.add(
            ChatMessage(
                user_id="u1",
                role="user",
                content="hey",
                created_at=base - timedelta(minutes=10),
            )
        )
        await s.commit()
    decision = await can_fire_proactive("u1", source="email", now=base)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_quiet_hours_fallback_uses_timezone_default(db, monkeypatch):
    """When sleep_time/wake_time are unset but timezone is set, default to
    midnight-7am in the user's local time (UTC ``now`` is converted via
    ZoneInfo before the time-of-day comparison)."""

    async def _no_facts(_user_id):  # noqa: ANN001
        return (None, None)

    async def _has_tz(_user_id):  # noqa: ANN001
        return "Asia/Singapore"

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _no_facts,
    )
    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_timezone",
        _has_tz,
    )
    # 18:00 UTC = 02:00 next-day Singapore (UTC+8) — inside the
    # 00:00-07:00 default quiet window. Must suppress.
    decision = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 18, 0)
    )
    assert decision.allowed is False
    assert "quiet" in decision.reason

    # 03:00 UTC = 11:00 same-day Singapore — outside quiet window. Allow.
    decision_day = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 3, 0)
    )
    assert decision_day.allowed is True


@pytest.mark.asyncio
async def test_no_quiet_hours_when_timezone_unset(db, monkeypatch):
    async def _no_facts(_user_id):  # noqa: ANN001
        return (None, None)

    async def _no_tz(_user_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _no_facts,
    )
    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_timezone",
        _no_tz,
    )
    decision = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 3, 0)
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_record_ping_persists_topic_key(db, _no_quiet_hours):
    from sqlalchemy import select

    await record_ping(
        "u1",
        source="email",
        message_ref="m1",
        topic_key="thread-A",
    )
    async with db() as s:
        rows = (
            await s.execute(select(ProactivePing).where(ProactivePing.user_id == "u1"))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].topic_key == "thread-A"
