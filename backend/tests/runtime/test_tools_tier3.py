"""Tier 3 tool palette — terminators (skip, kill_attention, reshape_attention)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from donna_runtime.tools_tier3 import (
    skip,
    kill_attention,
    reshape_attention,
    send_burst,
    quick_check,
    read_external,
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


@pytest.mark.asyncio
async def test_kill_attention_strips_whitespace_only_id():
    with pytest.raises(ValueError, match="attention_id"):
        await kill_attention(attention_id="   ", reason="x")


@pytest.mark.asyncio
async def test_reshape_attention_with_surface_level_canonical_value():
    out = await reshape_attention(
        attention_id="att_1",
        surface_level="urgent",
    )
    assert out["reshape_kwargs"]["surface_level"] == "urgent"


@pytest.mark.asyncio
async def test_skip_caps_reason_length():
    long_reason = "x" * 1000
    out = await skip(reason=long_reason)
    # Reason capped at 500 chars (the module-level _MAX_REASON_LEN).
    assert len(out["reason"]) == 500


@pytest.mark.asyncio
async def test_send_burst_push_default_quadrant():
    out = await send_burst(messages=[{"type": "text", "body": "hi"}])
    assert out["action"] == "ship"
    assert out["push"] is True
    assert out["surface_at"] is None


@pytest.mark.asyncio
async def test_send_burst_ambient_quadrant():
    out = await send_burst(
        messages=[{"type": "text", "body": "fyi"}],
        push=False,
    )
    assert out["action"] == "ship"
    assert out["push"] is False
    assert out["surface_at"] is None


@pytest.mark.asyncio
async def test_send_burst_hold_for_next_touch():
    out = await send_burst(
        messages=[{"type": "text", "body": "later"}],
        push=False,
        surface_at="next_user_touch",
    )
    assert out["surface_at"] == "next_user_touch"


@pytest.mark.asyncio
async def test_send_burst_morning_brief():
    out = await send_burst(
        messages=[{"type": "text", "body": "tomorrow"}],
        push=False,
        surface_at="morning_brief",
    )
    assert out["surface_at"] == "morning_brief"


@pytest.mark.asyncio
async def test_send_burst_rejects_push_with_surface_at():
    with pytest.raises(ValueError, match="surface_at requires push=False"):
        await send_burst(
            messages=[{"type": "text", "body": "x"}],
            push=True,
            surface_at="morning_brief",
        )


@pytest.mark.asyncio
async def test_send_burst_requires_messages():
    with pytest.raises(ValueError, match="messages"):
        await send_burst(messages=[])


@pytest.mark.asyncio
async def test_quick_check_requires_question():
    with pytest.raises(ValueError, match="question"):
        await quick_check(question="")


@pytest.mark.asyncio
async def test_quick_check_returns_results_shape(monkeypatch):
    """Stub the underlying exa search call."""
    async def _fake_search(*, query, num_results, **_kwargs):
        return [
            {"title": "A", "url": "https://a", "excerpt": "ex"},
            {"title": "B", "url": "https://b", "excerpt": "ex"},
        ]
    monkeypatch.setattr(
        "donna_runtime.tools_tier3._exa_search_for_quick_check",
        _fake_search,
    )

    out = await quick_check(question="is anthropic shipping today?")
    assert out["status"] == "ok"
    assert len(out["results"]) == 2
    assert out["results"][0]["url"] == "https://a"


@pytest.mark.asyncio
async def test_quick_check_caps_max_results():
    """max_results is hard-capped at 5 to prevent abuse."""
    with pytest.raises(ValueError, match="max_results"):
        await quick_check(question="x", max_results=99)


@pytest.mark.asyncio
async def test_read_external_unknown_source_raises():
    with pytest.raises(ValueError, match="source"):
        await read_external(source="bogus", ref="x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_read_external_gmail_thread_returns_stub():
    out = await read_external(source="gmail_thread", ref="thread_xyz")
    assert out["status"] in {"ok", "degraded", "no_fetcher"}
    assert out["source"] == "gmail_thread"
    assert out["ref"] == "thread_xyz"
