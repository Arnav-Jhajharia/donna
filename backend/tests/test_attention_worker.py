"""Attention worker dispatch tests.

Covers the propose/promote pass shape and the run_forever loop's
clock behavior. DB integration is out of scope here — we monkey-patch
the user lister and the propose/promote callees so tests run hermetic.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.memory.jobs import attention_worker as aw


@pytest.mark.unit
def test_run_propose_pass_returns_zero_with_no_active_users(monkeypatch):
    async def fake_list() -> list[str]:
        return []

    monkeypatch.setattr(aw, "_list_active_user_ids", fake_list)
    count = asyncio.run(aw.run_propose_pass())
    assert count == 0


@pytest.mark.unit
def test_run_propose_pass_calls_propose_per_user(monkeypatch):
    seen: list[str] = []

    async def fake_list() -> list[str]:
        return ["u1", "u2", "u3"]

    async def fake_propose(uid: str) -> list[Any]:
        seen.append(uid)
        return []

    monkeypatch.setattr(aw, "_list_active_user_ids", fake_list)
    monkeypatch.setattr(
        "donna.attention.propose.propose_and_shadow", fake_propose
    )

    count = asyncio.run(aw.run_propose_pass())
    assert count == 3
    assert sorted(seen) == ["u1", "u2", "u3"]


@pytest.mark.unit
def test_run_propose_pass_isolates_user_failures(monkeypatch):
    seen: list[str] = []

    async def fake_list() -> list[str]:
        return ["good", "bad", "good2"]

    async def fake_propose(uid: str) -> list[Any]:
        seen.append(uid)
        if uid == "bad":
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(aw, "_list_active_user_ids", fake_list)
    monkeypatch.setattr(
        "donna.attention.propose.propose_and_shadow", fake_propose
    )

    # Should not raise; bad user is logged and skipped.
    count = asyncio.run(aw.run_propose_pass())
    assert count == 3
    assert "good" in seen and "good2" in seen


@pytest.mark.unit
def test_run_promote_pass_invokes_run_shadow_cycle(monkeypatch):
    calls: list[Any] = []

    def fake_cycle() -> list[Any]:
        calls.append("called")
        return []

    monkeypatch.setattr(
        "donna.attention.promote.run_shadow_cycle", fake_cycle
    )
    count = asyncio.run(aw.run_promote_pass())
    assert count == 0
    assert calls == ["called"]


@pytest.mark.unit
def test_run_forever_fires_both_passes_immediately_then_cancels(monkeypatch):
    propose_calls = {"n": 0}
    promote_calls = {"n": 0}

    async def fake_propose(*, max_concurrent: int = 1) -> int:
        propose_calls["n"] += 1
        return 0

    async def fake_promote() -> int:
        promote_calls["n"] += 1
        return 0

    monkeypatch.setattr(aw, "run_propose_pass", fake_propose)
    monkeypatch.setattr(aw, "run_promote_pass", fake_promote)

    async def driver() -> None:
        # Big intervals so only the initial fire happens during the test.
        task = asyncio.create_task(
            aw.run_forever(
                poll_interval_s=0.01,
                propose_interval_s=3600,
                promote_interval_s=3600,
            )
        )
        # Yield control briefly so the loop body runs once.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())
    assert propose_calls["n"] == 1
    assert promote_calls["n"] == 1


@pytest.mark.unit
def test_run_forever_respects_independent_clocks(monkeypatch):
    """Promote fires more often than propose when its interval is shorter."""
    propose_calls = {"n": 0}
    promote_calls = {"n": 0}

    async def fake_propose(*, max_concurrent: int = 1) -> int:
        propose_calls["n"] += 1
        return 0

    async def fake_promote() -> int:
        promote_calls["n"] += 1
        return 0

    monkeypatch.setattr(aw, "run_propose_pass", fake_propose)
    monkeypatch.setattr(aw, "run_promote_pass", fake_promote)

    async def driver() -> None:
        task = asyncio.create_task(
            aw.run_forever(
                poll_interval_s=0.005,
                propose_interval_s=3600,  # never re-fires
                promote_interval_s=0.0,  # fires every tick
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())
    assert propose_calls["n"] == 1  # only the initial fire
    assert promote_calls["n"] >= 2  # multiple ticks
