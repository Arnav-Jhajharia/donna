"""Tier 3 tool palette — terminators (skip, kill_attention, reshape_attention)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from donna_runtime.tools_tier3 import (
    skip,
    kill_attention,
    reshape_attention,
)


@pytest.mark.asyncio
async def test_skip_returns_outcome_with_reason():
    out = await skip(reason="moment is dead")
    assert out["action"] == "skip"
    assert out["reason"] == "moment is dead"


@pytest.mark.asyncio
async def test_skip_rejects_empty_reason():
    with pytest.raises(ValueError, match="reason"):
        await skip(reason="")


@pytest.mark.asyncio
async def test_kill_attention_returns_outcome():
    out = await kill_attention(
        attention_id="att_1",
        reason="user already did the thing",
    )
    assert out["action"] == "kill"
    assert out["attention_id"] == "att_1"
    assert out["reason"] == "user already did the thing"


@pytest.mark.asyncio
async def test_kill_attention_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        await kill_attention(attention_id="att_1", reason="")


@pytest.mark.asyncio
async def test_reshape_attention_with_next_fire_at():
    fire_at = datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)
    out = await reshape_attention(
        attention_id="att_1",
        next_fire_at=fire_at,
    )
    assert out["action"] == "reshape"
    assert out["attention_id"] == "att_1"
    assert out["reshape_kwargs"]["next_fire_at"] == fire_at.isoformat()


@pytest.mark.asyncio
async def test_reshape_attention_requires_at_least_one_change():
    with pytest.raises(ValueError, match="at least one"):
        await reshape_attention(attention_id="att_1")
