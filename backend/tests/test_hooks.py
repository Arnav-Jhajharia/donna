"""Hook structural tests — verify each hook is safe to call without live IO.

The hooks degrade silently when their backing clients/DB are unavailable.
This test proves that invariant and the ALL_HOOKS manifest shape.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.memory.hooks import (
    ALL_HOOKS,
    extract_user_facts,
    ingest_to_graph,
    record_episode,
    save_chat_messages,
)


def test_all_hooks_registered():
    assert len(ALL_HOOKS) == 4
    assert save_chat_messages.run in ALL_HOOKS
    assert record_episode.run in ALL_HOOKS
    assert ingest_to_graph.run in ALL_HOOKS
    assert extract_user_facts.run in ALL_HOOKS


def test_hook_signatures_are_async():
    for h in ALL_HOOKS:
        assert asyncio.iscoroutinefunction(h)


def _ctx(**overrides):
    base = {
        "user_id": "",
        "inbound": "hi",
        "outbound": [],
        "tool_names": [],
        "terminator": "send_burst",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_hooks_noop_without_user_id():
    ctx = _ctx(user_id="")
    # Should not raise regardless of backing services.
    await save_chat_messages.run(ctx)
    await record_episode.run(ctx)
    await ingest_to_graph.run(ctx)
    await extract_user_facts.run(ctx)


@pytest.mark.asyncio
async def test_save_chat_messages_skips_when_already_persisted():
    ctx = _ctx(
        user_id="u1",
        inbound="already stored",
        outbound=["already stored too"],
        chat_already_persisted=True,
    )
    await save_chat_messages.run(ctx)


@pytest.mark.asyncio
async def test_ingest_skipped_when_gate_rejects(monkeypatch):
    """Gate rejects short inbound; graphiti ingest must not be called."""
    called = {"n": 0}

    async def _fake_ingest(**kwargs):
        called["n"] += 1
        return True

    from backend.memory.clients import graphiti as graphiti_mod

    monkeypatch.setattr(graphiti_mod, "ingest_episode", _fake_ingest)

    # 'hi' is < 20 chars → fast_reject
    ctx = _ctx(user_id="u1", inbound="hi")
    await ingest_to_graph.run(ctx)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_ingest_called_on_fast_accept(monkeypatch):
    called = {"n": 0, "kwargs": None}

    async def _fake_ingest(**kwargs):
        called["n"] += 1
        called["kwargs"] = kwargs
        return True

    from backend.memory.clients import graphiti as graphiti_mod

    monkeypatch.setattr(graphiti_mod, "ingest_episode", _fake_ingest)

    ctx = _ctx(
        user_id="u1",
        inbound="a" * 40,
        outbound=["one", "two"],  # multi-burst → fast_accept
    )
    await ingest_to_graph.run(ctx)
    assert called["n"] == 1
    assert called["kwargs"]["user_id"] == "u1"
    assert "USER:" in called["kwargs"]["content"]
    assert "DONNA:" in called["kwargs"]["content"]


@pytest.mark.asyncio
async def test_record_episode_degrades_without_client(monkeypatch):
    """When supermemory is unavailable, run() returns silently."""
    from backend.memory.clients import supermemory as sm_mod

    class _Fake:
        available = False

        async def add_episode(self, **kwargs):
            raise AssertionError("should not be called")

    monkeypatch.setattr(sm_mod, "get_memory_client", lambda: _Fake())
    monkeypatch.setattr(record_episode, "get_memory_client", lambda: _Fake())

    ctx = _ctx(user_id="u1", inbound="hello there", outbound=["hi"])
    await record_episode.run(ctx)  # should not raise


@pytest.mark.asyncio
async def test_record_episode_called_when_available(monkeypatch):
    seen = {"body": None, "user_id": None}

    class _Fake:
        available = True

        async def add_episode(self, user_id, content, **kwargs):
            seen["body"] = content
            seen["user_id"] = user_id
            return "mem-id"

    monkeypatch.setattr(record_episode, "get_memory_client", lambda: _Fake())

    ctx = _ctx(user_id="u1", inbound="moved to Tokyo last week", outbound=["noted"])
    await record_episode.run(ctx)
    assert seen["user_id"] == "u1"
    assert "USER: moved to Tokyo last week" in seen["body"]
    assert "DONNA: noted" in seen["body"]
