"""In-process pub/sub for manifest changes.

When ``upsert_manifest`` writes a fresh plan, it calls ``publish`` here.
SSE subscribers attached via the ``/api/dashboard/{user_id}/events``
endpoint get notified and the frontend re-fetches the manifest within
~1 second instead of waiting for the next 20s poll.

In-process only — does NOT propagate across multiple API pods. Fine
for single-pod / dev / pre-launch scale. When we shard the API across
Railway services we'll swap this for a Redis pubsub backend; the
subscriber API stays the same.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# user_id → set of asyncio.Queue subscribers
_subscribers: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)


def publish(user_id: str, kind: str = "manifest_changed") -> None:
    """Notify every subscriber for ``user_id``. Best-effort; never raises."""
    subs = _subscribers.get(user_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(kind)
        except asyncio.QueueFull:
            # Drop the oldest, keep the newest. SSE clients re-fetch
            # the manifest on any signal so missing one is harmless.
            try:
                q.get_nowait()
                q.put_nowait(kind)
            except Exception:
                pass


async def subscribe(user_id: str) -> AsyncIterator[str]:
    """Async generator yielding event kinds for ``user_id``.

    Wires a queue, yields events as they arrive, removes the queue
    when the consumer's coroutine exits (CancelledError or break).
    Use as the event source of an SSE StreamingResponse.
    """
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
    _subscribers[user_id].add(queue)
    try:
        while True:
            kind = await queue.get()
            yield kind
    finally:
        subs = _subscribers.get(user_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                _subscribers.pop(user_id, None)


def subscriber_count(user_id: str) -> int:
    """Test/observability helper."""
    return len(_subscribers.get(user_id, set()))
