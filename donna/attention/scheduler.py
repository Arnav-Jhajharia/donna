"""In-process scheduler for the proactive loop.

Runs two jobs on independent intervals:
  - propose_job (slow, LLM)   — scan ambient signal, author shadows
  - promote_job (fast, no LLM) — tick shadows, promote or archive

Pure asyncio; no new deps. Gated by `DONNA_ATTENTION_SCHEDULER=1` so
tests and one-shot CLI runs never fire these timers.

Production eventually wants per-user job rows in a durable queue; this
module is Phase 2 of the plan in SCHEDULING.md. The public surface here
(`Scheduler.start`, `Scheduler.stop`) is the same shape APScheduler
exposes, so the swap is mechanical.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from donna.attention.promote import run_shadow_cycle
from donna.attention.propose import propose_and_shadow

logger = logging.getLogger(__name__)

JobFn = Callable[[], Awaitable[None]]

DEFAULT_PROPOSE_INTERVAL_SEC = 30 * 60  # 30 min
DEFAULT_PROMOTE_INTERVAL_SEC = 15 * 60  # 15 min


@dataclass(frozen=True)
class Job:
    name: str
    interval_seconds: int
    fn: JobFn


class Scheduler:
    """Minimal asyncio interval scheduler."""

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        if self._tasks:
            raise RuntimeError("scheduler already started")
        self._stop_event = asyncio.Event()
        for job in self._jobs:
            self._tasks.append(asyncio.create_task(self._loop(job), name=job.name))
        logger.info("attention scheduler started: %s", [j.name for j in self._jobs])

    async def stop(self) -> None:
        if self._stop_event is None:
            return
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._stop_event = None

    async def _loop(self, job: Job) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await job.fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler job %s failed", job.name)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=job.interval_seconds
                )
            except asyncio.TimeoutError:
                pass


# -- Job factories -----------------------------------------------------------


def make_propose_job(user_id: str) -> JobFn:
    async def _job() -> None:
        logger.info("propose_job firing for user=%s", user_id)
        results = await propose_and_shadow(user_id)
        authored = sum(1 for r in results if r.attention is not None)
        logger.info(
            "propose_job: %d candidates, %d shadowed", len(results), authored
        )

    return _job


def make_promote_job(user_id: str | None = None) -> JobFn:
    async def _job() -> None:
        logger.info("promote_job firing for user=%s", user_id or "*")
        results = run_shadow_cycle(user_id=user_id)
        promoted = sum(1 for r in results if r.action == "promoted")
        archived = sum(1 for r in results if r.action == "archived")
        logger.info(
            "promote_job: ticked %d shadows, promoted %d, archived %d",
            len(results),
            promoted,
            archived,
        )

    return _job


def build_default_scheduler(
    user_id: str,
    *,
    propose_interval_sec: int = DEFAULT_PROPOSE_INTERVAL_SEC,
    promote_interval_sec: int = DEFAULT_PROMOTE_INTERVAL_SEC,
) -> Scheduler:
    return Scheduler(
        jobs=[
            Job("propose", propose_interval_sec, make_propose_job(user_id)),
            Job("promote", promote_interval_sec, make_promote_job(user_id)),
        ]
    )


# -- Env-gated entrypoint ----------------------------------------------------


def enabled() -> bool:
    return os.environ.get("DONNA_ATTENTION_SCHEDULER") == "1"
