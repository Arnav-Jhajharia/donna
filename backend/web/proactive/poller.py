"""Cadence-aware /search poller — the proactive watch primary path.

For each active subscription, runs ``/search`` at the cadence picked by
the deriver (``daily``/``weekly``/``monthly``), dedupes URLs against
rows already in ``proactive_signals``, and enqueues new hits.

This is the cost-conscious path. Websets+monitors at Exa cost ~10
credits per delivered row; ``/search`` costs ~5 credits per call
regardless of ``numResults``. For our 8000-credit/$49 budget, polling
is 15-30x cheaper than monitor-driven curation. The webset+monitor
provisioning code path is deprecated; the legacy webhook receiver
(``api/exa_webhook.py``) stays in place but should never fire under
the current architecture.

Cadence-to-interval map:
    daily   = 24h  (caller must run loop ≤1h to hit it accurately)
    weekly  = 7d
    monthly = 30d

Each tick: pick subs whose ``last_hit_at + cadence_interval <= now``
(or whose ``last_hit_at`` is NULL → never polled), call ``/search``,
write new URLs to ``proactive_signals``, bump ``last_hit_at``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from backend.web.client import have_exa_key
from backend.web.proactive.store import SignalQueueRepo
from db.models import ProactiveSignal, ProactiveSubscription
from db.session import async_session

logger = logging.getLogger(__name__)


_CADENCE_TO_INTERVAL: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
_DEFAULT_CADENCE = "weekly"


def _is_due(sub: ProactiveSubscription, now: datetime) -> bool:
    """True when this sub's cadence interval has elapsed since last poll.

    Subs that have never been polled (``last_hit_at IS NULL``) are due
    immediately. Unknown cadences fall back to weekly.
    """
    if sub.last_hit_at is None:
        return True
    interval = _CADENCE_TO_INTERVAL.get(
        (sub.cadence or "").strip().lower(),
        _CADENCE_TO_INTERVAL[_DEFAULT_CADENCE],
    )
    return (now - sub.last_hit_at) >= interval


@dataclass(frozen=True)
class PollSummary:
    """Result of one ``poll_pending_subscriptions`` pass."""

    user_id: str
    polled: int
    new_signals: int
    failed: int


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _existing_urls_for_subscription(
    subscription_id: str,
) -> set[str]:
    """URLs already enqueued under this subscription, for dedup."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProactiveSignal.payload).where(
                    ProactiveSignal.subscription_id == subscription_id,
                )
            )
        ).all()
    out: set[str] = set()
    for r in rows:
        payload = r[0] or {}
        url = (
            (payload.get("url") if isinstance(payload, dict) else None)
            or ""
        )
        if isinstance(url, str) and url.strip():
            out.add(url.strip())
    return out


async def poll_pending_subscriptions(
    user_id: str,
    *,
    max_results_per_sub: int = 2,
) -> PollSummary:
    """For each ACTIVE + DUE sub, run ``/search`` and enqueue new URLs.

    "Due" means ``last_hit_at + cadence_interval <= now`` (or
    ``last_hit_at`` is NULL). Subs whose cadence interval hasn't elapsed
    are skipped — that's how we honor the deriver's daily/weekly/monthly
    choice without paying credits to over-poll.

    Cost shape: each ``/search`` costs ~5 credits at Exa, regardless of
    ``numResults``. We default to 2 results per call to keep judge load
    modest downstream — the drain trigger judges every URL we enqueue.

    Never raises — per-sub failures are logged and counted. No-op when
    ``EXA_API_KEY`` missing or the operator has set
    ``DONNA_EXA_AUTOMATION_PAUSE=1`` (emergency cost stop).
    """
    from backend.web.proactive.cost_gate import exa_automation_paused

    if exa_automation_paused():
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)
    if not have_exa_key():
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)

    now = _utcnow_naive()
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(ProactiveSubscription).where(
                        ProactiveSubscription.user_id == user_id,
                        ProactiveSubscription.active.is_(True),
                    )
                )
            ).scalars()
        )

    due_rows = [r for r in rows if _is_due(r, now)]
    if not due_rows:
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)

    queue = SignalQueueRepo()
    polled = 0
    new_signals = 0
    failed = 0

    # System B routing: each due sub gets wrapped as a single-element
    # GeneratedQuery batch and resolved through fetch_for_queries (one
    # /search + one /findSimilar per sub). Cost per due sub: ~10 credits.
    from backend.web.proactive.system_b.fetcher import fetch_for_queries
    from backend.web.proactive.system_b.query_gen import GeneratedQuery

    for sub in due_rows:
        polled += 1
        gq = GeneratedQuery(
            text=sub.description,
            angle="direct",
            cadence=(sub.cadence or "weekly"),
            ties_to=f"proactive_subscription intent={sub.intent_key}",
            expand_with_similar=True,
        )
        try:
            fetched_items, _summary = await fetch_for_queries(
                [gq], user_id=user_id, skip_dedup=True
            )
        except Exception:
            logger.exception(
                "poll_pending_subscriptions: System B fetch failed user=%s intent=%s",
                user_id[:8] if user_id else "?",
                sub.intent_key,
            )
            failed += 1
            continue

        # Bump last_hit_at after EVERY successful fetch regardless of
        # whether any new URLs came back. Otherwise a sub that returns
        # no new results would stay "due" forever under cadence-aware
        # polling — and we'd burn ~10 credits/hour on the same dead
        # query.
        async with async_session() as session:
            await session.execute(
                update(ProactiveSubscription)
                .where(ProactiveSubscription.id == sub.id)
                .values(last_hit_at=_utcnow_naive())
            )
            await session.commit()

        if not fetched_items:
            continue

        seen = await _existing_urls_for_subscription(sub.id)

        enqueued_for_sub = 0
        for it in fetched_items:
            if it.url in seen:
                continue
            await queue.enqueue(
                user_id=user_id,
                subscription_id=sub.id,
                intent_key=sub.intent_key,
                payload=it.to_signal_payload(),
            )
            seen.add(it.url)
            enqueued_for_sub += 1

        new_signals += enqueued_for_sub

    return PollSummary(
        user_id=user_id,
        polled=polled,
        new_signals=new_signals,
        failed=failed,
    )
