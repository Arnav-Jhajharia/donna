"""Store + tool handler tests. LLM mocked so tests run offline."""
from __future__ import annotations

import asyncio

import pytest

from donna.attention.schema import AttentionStatus
from donna.attention.store import AttentionStore
from donna.attention.tools import (
    create_attention,
    get_attention,
    list_attentions,
    pause_attention,
    resolve_attention,
    resume_attention,
    tick_attention,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = AttentionStore(path=tmp_path / "attentions.json")
    monkeypatch.setattr(
        "donna.attention.tools.AttentionStore",
        lambda: s,
    )
    async def fake_none(**kwargs):
        return None
    monkeypatch.setattr(
        "backend.memory.retrieval.structured.call_structured", fake_none
    )
    return s


@pytest.mark.unit
def test_create_persists_and_lists(store):
    result = asyncio.run(create_attention("keep an eye on Poke", user_id="cli-user"))
    assert result.attention.status is AttentionStatus.LIVE
    listed = list_attentions()
    assert len(listed) == 1
    assert listed[0].id == result.attention.id


@pytest.mark.unit
def test_pause_resume_resolve(store):
    r = asyncio.run(create_attention("keep an eye on Poke", user_id="cli-user"))
    aid = str(r.attention.id)
    assert pause_attention(aid).status is AttentionStatus.PAUSED
    assert resume_attention(aid).status is AttentionStatus.LIVE
    assert resolve_attention(aid).status is AttentionStatus.RESOLVED


@pytest.mark.unit
def test_tick_appends_history_and_bumps_update_count(store):
    r = asyncio.run(create_attention("keep an eye on Poke", user_id="cli-user"))
    aid = str(r.attention.id)
    tick_attention(aid)
    tick_attention(aid)
    refreshed = get_attention(aid)
    assert refreshed.update_count == 2
    assert len(store.ticks(aid)) == 2


@pytest.mark.unit
def test_ping_create_short_circuits_without_llm(store):
    # _looks_like_bare_reminder should match; no LLM call needed.
    r = asyncio.run(create_attention("remind me to call mom at 6pm", user_id="cli-user"))
    assert r.attention.spec.card.value == "ping"
    assert r.authored_via == "ping_shortcircuit"


@pytest.mark.unit
def test_ping_dedup_reuses_recent_match(store):
    """Second sleep PING within the dedup window reuses the first."""
    first = asyncio.run(
        create_attention("remind me in 15 minutes to sleep", user_id="cli-user")
    )
    assert first.reused is False

    second = asyncio.run(
        create_attention("remind me in 30 minutes to sleep", user_id="cli-user")
    )
    assert second.reused is True
    # Same row: same id.
    assert second.attention.id == first.attention.id
    # And the store still contains exactly one PING for sleep.
    listed = list_attentions(status=AttentionStatus.LIVE)
    sleep_pings = [
        a
        for a in listed
        if a.spec.card.value == "ping"
        and "sleep" in (a.spec.subject.name or "").lower()
    ]
    assert len(sleep_pings) == 1


@pytest.mark.unit
def test_ping_dedup_does_not_collapse_different_subjects(store):
    """Different subjects (sleep vs water) must NOT dedup against each other."""
    sleep = asyncio.run(
        create_attention("remind me in 15 minutes to sleep", user_id="cli-user")
    )
    water = asyncio.run(
        create_attention("remind me in 10 minutes to drink water", user_id="cli-user")
    )
    assert sleep.reused is False
    assert water.reused is False
    assert water.attention.id != sleep.attention.id


@pytest.mark.unit
def test_non_ping_create_is_not_deduped(store):
    """Tally cards never trigger the PING dedup path even with same subject."""
    # Both create_attention calls produce the same intent shape but the
    # author returns the same TALLY card type; dedup is PING-only, so
    # both rows should land.
    first = asyncio.run(
        create_attention("track my hydration daily", user_id="cli-user")
    )
    second = asyncio.run(
        create_attention("track my hydration daily", user_id="cli-user")
    )
    assert first.reused is False
    # If the author produced TALLY for both, they should NOT collapse.
    if first.attention.spec.card.value != "ping":
        assert second.reused is False
