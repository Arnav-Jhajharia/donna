"""Fresh-signal pre-fetcher — conditional re-fetch by speech_act + age."""
from __future__ import annotations

import pytest

from proactive.events import ProactiveEvent
from proactive.fresh_signal import should_prefetch, fetch_for_event


def _event(speech_act, age_minutes=120, source="email"):
    return ProactiveEvent(
        user_id="u1",
        source=source,
        source_ref="r",
        topic_key="t",
        speech_act=speech_act,
        signals={"event_age_minutes": age_minutes},
    )


def test_dont_forget_does_not_prefetch():
    assert not should_prefetch(_event("dont_forget"))


def test_thought_youd_want_does_not_prefetch():
    assert not should_prefetch(_event("thought_youd_want"))


def test_i_noticed_does_not_prefetch():
    assert not should_prefetch(_event("i_noticed"))


def test_heads_up_recent_event_does_not_prefetch():
    assert not should_prefetch(_event("heads_up", age_minutes=30))


def test_heads_up_stale_event_prefetches():
    assert should_prefetch(_event("heads_up", age_minutes=120))


def test_now_the_moment_stale_event_prefetches():
    assert should_prefetch(_event("now_the_moment", age_minutes=120))


@pytest.mark.asyncio
async def test_fetch_for_event_falls_back_for_unknown_source():
    """Sources without a fetcher return a benign error result, not a raise."""
    e = _event("heads_up", source="pattern")
    result = await fetch_for_event(e)
    assert result["status"] == "no_fetcher"


@pytest.mark.asyncio
async def test_fetch_for_event_returns_ok_status_for_known_source():
    """Phase 1 stubs return status=ok for the four wired sources."""
    e = _event("heads_up", source="email")
    result = await fetch_for_event(e)
    assert result["status"] == "ok"
    assert "fetched_at" in result


def test_threshold_boundary_at_60_minutes_prefetches():
    """should_prefetch uses >=, so age=60 (the exact threshold) prefetches."""
    assert should_prefetch(_event("heads_up", age_minutes=60))


@pytest.mark.asyncio
async def test_fetch_for_event_swallows_exceptions():
    """Per-source failures degrade rather than raise."""
    import proactive.fresh_signal as fs

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated source failure")

    # Monkey-patch one fetcher temporarily
    original = fs._fetch_email
    fs._fetch_email = boom
    try:
        e = _event("heads_up", source="email")
        result = await fetch_for_event(e)
        assert result["status"] == "degraded"
        assert "error" in result
    finally:
        fs._fetch_email = original
