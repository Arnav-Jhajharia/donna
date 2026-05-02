"""Polling fallback for users without Exa websets access.

Free-tier Exa accounts can call ``/search`` but not ``/websets/v0/*``.
This module runs a periodic ``/search`` per active-but-unprovisioned
subscription, dedupes URLs against rows already in ``proactive_signals``
for that subscription, and enqueues new hits.

Coexists with the webset/monitor provisioning path:
- If the subscription has ``webset_id`` set, Exa is pushing for us; the
  poller skips it.
- If the subscription has ``webset_id IS NULL`` (free-tier or pending
  upgrade), the poller fills the gap by pulling.

Once a user upgrades to a tier that supports websets, the next
``provision_pending_websets`` call sets ``webset_id`` and the poller
stops polling that subscription. No code or data migration needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from backend.web.client import exa_search, exa_webset_items, have_exa_key
from backend.web.proactive.store import SignalQueueRepo
from db.models import ProactiveSignal, ProactiveSubscription
from db.session import async_session

logger = logging.getLogger(__name__)


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
    max_results_per_sub: int = 5,
) -> PollSummary:
    """For each active sub, pull fresh items and enqueue any new URLs
    as ``proactive_signals``.

    Two modes, picked per-subscription:
      - sub HAS webset_id  -> GET /websets/v0/websets/{id}/items
        Reads the curated list Exa is maintaining for us. Cheap and
        accurate; this is how we get monitor-fed items into the queue
        without a public webhook URL.
      - sub HAS NO webset_id -> POST /search
        Free-tier fallback for subs that haven't been provisioned yet.

    Never raises - failures per subscription are logged and counted.
    No-op when EXA_API_KEY is missing or when the operator has set
    DONNA_EXA_AUTOMATION_PAUSE=1 (emergency cost stop).
    """
    from backend.web.proactive.cost_gate import exa_automation_paused

    if exa_automation_paused():
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)
    if not have_exa_key():
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)

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

    if not rows:
        return PollSummary(user_id, polled=0, new_signals=0, failed=0)

    queue = SignalQueueRepo()
    polled = 0
    new_signals = 0
    failed = 0

    for sub in rows:
        polled += 1
        try:
            if sub.webset_id:
                items_resp = await exa_webset_items(
                    sub.webset_id, limit=max_results_per_sub
                )
                items_raw = (
                    items_resp.get("data")
                    if isinstance(items_resp, dict)
                    else None
                ) or []
                # webset items wrap the source page under .properties.url etc.
                # Normalize to the same shape /search returns.
                normalized = []
                for it in items_raw:
                    if not isinstance(it, dict):
                        continue
                    props = it.get("properties") or {}
                    url = (
                        props.get("url")
                        or it.get("url")
                        or ""
                    )
                    title = (
                        props.get("title")
                        or it.get("title")
                        or url
                    )
                    snippet = (
                        props.get("description")
                        or props.get("summary")
                        or ""
                    )
                    if url:
                        normalized.append({
                            "url": url,
                            "title": title,
                            "highlights": [snippet] if snippet else [],
                            "publishedDate": props.get("publishedDate"),
                        })
                res = {"results": normalized}
            else:
                res = await exa_search(
                    sub.description,
                    num_results=max_results_per_sub,
                    search_type="auto",
                )
        except Exception:
            logger.exception(
                "poll_pending_subscriptions: pull failed user=%s intent=%s mode=%s",
                user_id[:8] if user_id else "?",
                sub.intent_key,
                "webset" if sub.webset_id else "search",
            )
            failed += 1
            continue

        items = res.get("results") if isinstance(res, dict) else None
        if not isinstance(items, list) or not items:
            continue

        seen = await _existing_urls_for_subscription(sub.id)

        enqueued_for_sub = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            if url in seen:
                continue
            await queue.enqueue(
                user_id=user_id,
                subscription_id=sub.id,
                intent_key=sub.intent_key,
                payload=item,
            )
            seen.add(url)
            enqueued_for_sub += 1

        new_signals += enqueued_for_sub

        if enqueued_for_sub:
            async with async_session() as session:
                await session.execute(
                    update(ProactiveSubscription)
                    .where(ProactiveSubscription.id == sub.id)
                    .values(last_hit_at=_utcnow_naive())
                )
                await session.commit()

    return PollSummary(
        user_id=user_id,
        polled=polled,
        new_signals=new_signals,
        failed=failed,
    )
