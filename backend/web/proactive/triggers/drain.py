"""Drain trigger.

Reads pending ``proactive_signals`` rows for a user, summarizes them
into a ``signal_queue``, fires ``run_proactive_tick(trigger="drain")``,
then marks the signals consumed so they don't re-fire.

Cadence is owned by the worker (not this module) - typical scheduling
is once every 4 hours per active user, plus a soft jitter to avoid
thundering herd. The drain trigger is cheap when the queue is empty;
it returns early without touching the brain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from backend.web.proactive.runner import run_proactive_tick
from backend.web.proactive.store import SignalQueueRepo
from backend.web.proactive.types import SignalSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrainDecision:
    """What ``maybe_drain_signals`` did, for tests + traces."""

    user_id: str
    signals_drained: int
    moves_emitted: int
    drafts_delivered: int


def _summarize_signal(
    payload: dict[str, Any], intent_key: str, signal_id: str
) -> SignalSummary:
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    highlights = payload.get("highlights") or []
    snippet = ""
    if isinstance(highlights, list) and highlights:
        snippet = " | ".join(str(h).strip() for h in highlights[:2])
    elif payload.get("text"):
        snippet = str(payload.get("text"))[:300]
    published = payload.get("publishedDate")
    return SignalSummary(
        signal_id=signal_id,
        intent_key=intent_key,
        title=title,
        url=url,
        snippet=snippet,
        published=str(published) if published else None,
    )


async def maybe_drain_signals(
    *,
    user_id: str,
    delivery_mode: Literal["shadow", "live", "none"] = "shadow",
    max_signals: int = 25,
) -> DrainDecision:
    """Drain pending Exa monitor hits and run one drain tick.

    No-op when the queue is empty. Marks all drained signals consumed
    regardless of judge verdicts - the queue is a buffer, not a retry
    log.
    """
    queue = SignalQueueRepo()
    pending = await queue.drain_pending(user_id, limit=max_signals)
    if not pending:
        return DrainDecision(
            user_id=user_id,
            signals_drained=0,
            moves_emitted=0,
            drafts_delivered=0,
        )

    summaries = tuple(
        _summarize_signal(p.payload, p.intent_key, p.id) for p in pending
    )

    try:
        tick = await run_proactive_tick(
            user_id=user_id,
            trigger="drain",
            signal_queue=summaries,
            delivery_mode=delivery_mode,
        )
    except Exception:
        logger.exception(
            "maybe_drain_signals: tick failed user=%s",
            user_id[:8] if user_id else "?",
        )
        # Still mark consumed - we don't want to re-judge the same hits
        # next tick. If something went wrong the operator can re-enqueue.
        await queue.mark_consumed([p.id for p in pending])
        return DrainDecision(
            user_id=user_id,
            signals_drained=len(pending),
            moves_emitted=0,
            drafts_delivered=0,
        )

    drafts = sum(1 for r, v in tick.verdicts if v.decision == "send")
    await queue.mark_consumed([p.id for p in pending])
    return DrainDecision(
        user_id=user_id,
        signals_drained=len(pending),
        moves_emitted=len(tick.moves_emitted),
        drafts_delivered=drafts,
    )
