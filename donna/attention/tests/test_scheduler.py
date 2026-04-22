"""Tests for the asyncio interval scheduler."""
from __future__ import annotations

import asyncio

import pytest

from donna.attention.scheduler import Job, Scheduler, enabled


@pytest.mark.unit
def test_enabled_respects_env(monkeypatch):
    monkeypatch.delenv("DONNA_ATTENTION_SCHEDULER", raising=False)
    assert enabled() is False
    monkeypatch.setenv("DONNA_ATTENTION_SCHEDULER", "1")
    assert enabled() is True
    monkeypatch.setenv("DONNA_ATTENTION_SCHEDULER", "0")
    assert enabled() is False


@pytest.mark.unit
def test_scheduler_fires_job_multiple_times():
    counter = {"n": 0}

    async def job() -> None:
        counter["n"] += 1

    async def run() -> None:
        # Very short interval so we get several fires in the test window.
        sched = Scheduler([Job("tick", 0, job)])
        await sched.start()
        await asyncio.sleep(0.05)
        await sched.stop()

    asyncio.run(run())
    # At least a few ticks. Not asserting an exact count — scheduler
    # cadence depends on event-loop scheduling.
    assert counter["n"] >= 2


@pytest.mark.unit
def test_scheduler_isolates_job_failures():
    calls = {"bad": 0, "good": 0}

    async def bad() -> None:
        calls["bad"] += 1
        raise RuntimeError("boom")

    async def good() -> None:
        calls["good"] += 1

    async def run() -> None:
        sched = Scheduler([Job("bad", 0, bad), Job("good", 0, good)])
        await sched.start()
        await asyncio.sleep(0.05)
        await sched.stop()

    asyncio.run(run())
    # Both jobs keep firing despite bad raising every cycle.
    assert calls["bad"] >= 2
    assert calls["good"] >= 2


@pytest.mark.unit
def test_scheduler_cannot_double_start():
    async def job() -> None:
        pass

    async def run() -> None:
        sched = Scheduler([Job("j", 60, job)])
        await sched.start()
        try:
            with pytest.raises(RuntimeError):
                await sched.start()
        finally:
            await sched.stop()

    asyncio.run(run())


@pytest.mark.unit
def test_stop_before_start_is_noop():
    async def run() -> None:
        sched = Scheduler([])
        await sched.stop()  # should not raise

    asyncio.run(run())
