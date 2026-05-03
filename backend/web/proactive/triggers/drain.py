"""Drain trigger.

Reads pending ``proactive_signals`` rows for a user and judges each
hit directly via the worth-telling judge. Greenlit verdicts flow through
the standard delivery layer; everything else is silenced. All drained
signals are marked consumed regardless of verdict - the queue is a
buffer, not a retry log.

Cadence is owned by the worker (not this module) - typical scheduling
is once every 4-10 hours per active user. Drain is cheap when the queue
is empty; it returns early without touching the brain.

Architectural note: each pending signal IS a candidate the judge must
score. Earlier shape passed the queue as context to ``run_proactive_tick``
which only judged moves the brain emitted; that meant a queue full of
real Exa hits could go entirely unjudged when the brain decided "the
queue is the answer." Now the drain trigger judges each signal directly
by synthesizing a ProactiveMove + ProactiveResult per signal. The brain
remains useful for FRESH-move generation in future trigger types
(morning, pre_event); for drain it is bypassed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from backend.web.proactive.delivery import deliver_drafts
from backend.web.proactive.gates import CostBudget
from backend.web.proactive.judge import judge_results
from backend.web.proactive.runner import build_context
from backend.web.proactive.store import (
    DailyCountRepo,
    PostgresDedupStore,
    SignalQueueRepo,
)
from backend.web.proactive.types import (
    ProactiveMove,
    ProactiveResult,
    SignalSummary,
)

logger = logging.getLogger(__name__)


# Hard ceiling on proactive messages a user can receive per local day.
# Override per-deploy via ``DONNA_PROACTIVE_DAILY_CAP``. Set to a low
# number for "quiet companion" UX; raise if the user has explicitly
# opted into more chatter. Counts both shadow and live deliveries
# against the same budget — once the cap is hit, everything else
# this calendar-day gets silenced regardless of judge verdict.
import os as _os
_DEFAULT_DAILY_CAP = 4
try:
    DAILY_PROACTIVE_CAP = max(0, int(
        _os.environ.get("DONNA_PROACTIVE_DAILY_CAP") or _DEFAULT_DAILY_CAP
    ))
except ValueError:
    DAILY_PROACTIVE_CAP = _DEFAULT_DAILY_CAP


@dataclass(frozen=True)
class DrainDecision:
    """What ``maybe_drain_signals`` did, for tests + traces."""

    user_id: str
    signals_drained: int
    moves_emitted: int
    drafts_delivered: int
    cap_remaining: int = -1  # -1 = unknown / not enforced


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


def _signal_to_candidate(
    signal_id: str,
    intent_key: str,
    payload: dict[str, Any],
) -> tuple[ProactiveMove, ProactiveResult]:
    """Wrap a queue signal as a ProactiveMove + ProactiveResult so the
    judge can score it the same way it scores brain-emitted moves.
    """
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    # The query string is for audit/logging; we are not executing this
    # move, just judging the result that already came in. Use the
    # title (multi-word) so the gates' min-tokens-for-search heuristic
    # doesn't drop the candidate before the judge sees it.
    audit_query = title or url or intent_key
    move = ProactiveMove(
        rationale=f"exa hit on watch {intent_key}",
        tool="search",  # type: ignore[arg-type]
        query=audit_query,
        dedup_key=f"signal:{signal_id}",
        hypothesis=f"a new external item matches the user's standing watch '{intent_key}'",
        user_signal=f"user has an active subscription with intent_key={intent_key}",
        payoff_if_hit=f"user gets to react to '{title or url}' before stumbling on it elsewhere",
    )
    result = ProactiveResult(
        move=move,
        status="ok",  # type: ignore[arg-type]
        payload={"results": [payload]},
        elapsed_ms=0,
    )
    return move, result


async def maybe_drain_signals(
    *,
    user_id: str,
    delivery_mode: Literal["shadow", "live", "none"] = "shadow",
    max_signals: int = 25,
    budget: CostBudget = CostBudget(),
) -> DrainDecision:
    """Drain pending signals, judge each one, deliver greenlit drafts.

    Marks every drained signal consumed regardless of verdict. Returns
    a DrainDecision summary. Never raises.
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

    candidates: list[tuple[ProactiveMove, ProactiveResult]] = [
        _signal_to_candidate(p.id, p.intent_key, p.payload) for p in pending
    ]

    try:
        ledger = PostgresDedupStore()
        signal_queue_for_ctx = tuple(
            _summarize_signal(p.payload, p.intent_key, p.id) for p in pending
        )
        context = await build_context(
            user_id=user_id,
            trigger="drain",
            signal_queue=signal_queue_for_ctx,
        )
        # Judge every candidate. Budget caps DELIVERY, not judging - we
        # want the judge to see everything and silence most; a small
        # per-turn cap then trims the (typically tiny) send list.
        all_results = [r for _, r in candidates]
        verdicts = await judge_results(context=context, results=all_results)
    except Exception:
        logger.exception(
            "maybe_drain_signals: judge failed user=%s",
            user_id[:8] if user_id else "?",
        )
        await queue.mark_consumed([p.id for p in pending])
        return DrainDecision(
            user_id=user_id,
            signals_drained=len(pending),
            moves_emitted=0,
            drafts_delivered=0,
        )

    # Daily cap: count proactive messages already delivered today.
    # Once the cap is reached, everything else is silenced regardless
    # of judge verdict. This is the dominant rate-limiter — per-turn
    # cap by itself only limits within ONE drain, not across drains.
    from datetime import datetime as _dt
    daily_repo = DailyCountRepo()
    local_date = _dt.now().strftime("%Y-%m-%d")
    try:
        sent_today = await daily_repo.get(user_id, local_date)
    except Exception:
        sent_today = 0
    cap_remaining = max(0, DAILY_PROACTIVE_CAP - int(sent_today or 0))

    # Per-turn cap (within a single drain) THEN daily cap.
    sends = [(r, v) for r, v in verdicts if v.decision == "send"]
    per_turn = min(max(0, int(budget.per_turn)), cap_remaining)
    capped_sends = sends[:per_turn]
    capped_keys = {r.move.dedup_key for r, _ in capped_sends}

    daily_cap_silence_reason = (
        f"daily-cap reached ({DAILY_PROACTIVE_CAP}/day, sent={sent_today})"
        if cap_remaining == 0 else None
    )
    final_verdicts = []
    for r, v in verdicts:
        if v.decision != "send":
            final_verdicts.append((r, v))
            continue
        if r.move.dedup_key in capped_keys:
            final_verdicts.append((r, v))
            continue
        reason = daily_cap_silence_reason or "per-turn cap"
        final_verdicts.append((r, v.__class__(decision="silence", reason=reason)))

    delivered = 0
    if delivery_mode in {"shadow", "live"}:
        try:
            delivered = await deliver_drafts(
                user_id=user_id,
                verdicts=final_verdicts,
                mode=delivery_mode,  # type: ignore[arg-type]
            )
        except Exception:
            logger.exception(
                "maybe_drain_signals: deliver_drafts failed user=%s",
                user_id[:8] if user_id else "?",
            )

    now_ts = time.time()
    for r, v in final_verdicts:
        if v.decision == "send":
            try:
                await daily_repo.bump(user_id, local_date, by=1)
                await ledger.mark_async(user_id, r.move.dedup_key, now=now_ts)
            except Exception:
                logger.exception(
                    "maybe_drain_signals: bump/mark failed user=%s dedup=%s",
                    user_id[:8],
                    r.move.dedup_key,
                )

    await queue.mark_consumed([p.id for p in pending])

    return DrainDecision(
        user_id=user_id,
        signals_drained=len(pending),
        moves_emitted=len(all_results),
        drafts_delivered=delivered,
        cap_remaining=max(0, cap_remaining - delivered),
    )
