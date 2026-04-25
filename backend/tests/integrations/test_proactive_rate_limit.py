"""Quota + cooldown + quiet-hours gating for proactive pings."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.integrations.proactive_rate_limit import (
    can_fire_proactive,
    record_ping,
)


@pytest.fixture
def _no_quiet_hours(monkeypatch):
    async def _none(_user_id):  # noqa: ANN001
        return (None, None)

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _none,
    )


@pytest.mark.asyncio
async def test_can_fire_when_quiet_no_history(db, _no_quiet_hours):
    decision = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 10, 0)
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_quota_capped_at_3_per_day(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 9, 0)
    for h in (9, 11, 14):
        await record_ping(
            "u1",
            source="email",
            message_ref=f"m{h}",
            at=base.replace(hour=h),
        )
    decision = await can_fire_proactive(
        "u1", source="email", now=base.replace(hour=15)
    )
    assert decision.allowed is False
    assert "quota" in decision.reason


@pytest.mark.asyncio
async def test_30min_cooldown(db, _no_quiet_hours):
    base = datetime(2026, 4, 25, 9, 0)
    await record_ping("u1", source="email", message_ref="m1", at=base)
    decision = await can_fire_proactive(
        "u1", source="email", now=base + timedelta(minutes=10)
    )
    assert decision.allowed is False
    assert "cooldown" in decision.reason


@pytest.mark.asyncio
async def test_quiet_hours_blocks(db, monkeypatch):
    async def _quiet(_user_id):  # noqa: ANN001
        return ("23:00", "07:00")

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _quiet,
    )
    decision = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 2, 30)
    )
    assert decision.allowed is False
    assert "quiet" in decision.reason
