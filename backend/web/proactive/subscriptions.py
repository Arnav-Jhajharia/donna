"""Subscription lifecycle: reconcile per-user watch_for_tomorrow against
``proactive_subscriptions`` rows, create webset+monitor in Exa,
record monitor hits.

This module is the bridge between the nightly Living Profile synthesis
and the always-on Exa subscription layer. ``reconcile_subscriptions``
is called from synthesis_worker after morning_runner; it does the table
diff but does NOT call Exa. ``provision_pending_websets`` walks rows
with ``webset_id IS NULL`` and provisions them — separated so the DB
diff stays cheap and Exa calls are bounded.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from backend.web.client import (
    exa_monitor_create,
    exa_webset_create,
    have_exa_key,
)
from backend.web.proactive.store import SignalQueueRepo
from db.models import ProactiveSubscription, User
from db.session import async_session

logger = logging.getLogger(__name__)

# Delay between provisioning iterations to avoid tripping Exa's
# concurrent-op cap on Starter (typically 1-3 in flight). Tunable;
# 3 seconds is comfortable for serial creates of ~5 subs.
_PROVISION_DELAY_S = 3.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def intent_key_for_watch_line(line: str) -> str:
    """Stable intent key from a free-text watch line.

    Lowercased, alnum-collapsed, prefixed ``watch:``, hash-suffixed for
    uniqueness when two lines collapse to the same slug.
    """
    raw = (line or "").strip().lower()
    slug = _NON_ALNUM.sub("_", raw).strip("_")[:60] or "anon"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"watch:{slug}:{digest}"


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _monitor_webhook_fields() -> dict[str, Any] | None:
    """Build the webhook-delivery fields for a new Exa monitor.

    Reads EXA_WEBHOOK_BASE_URL (e.g. https://donna.example.com) and
    appends the canonical callback path. Returns None when the env var
    is unset, in which case the monitor runs at Exa but does not
    deliver to us — useful for dev environments where the webhook isn't
    reachable from public internet.

    The exact field name on Exa's monitor body is currently
    ``webhookUrl``; if Exa changes the API shape this is the only place
    that needs an update.
    """
    base = (os.environ.get("EXA_WEBHOOK_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    return {"webhookUrl": f"{base}/api/exa/monitor_callback"}


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileSummary:
    """Trace-friendly summary of one reconcile pass."""

    user_id: str
    created: int
    deactivated: int
    skipped_over_budget: int


async def reconcile_subscriptions(
    user_id: str,
    *,
    max_active: int = 5,
    watches_override: list[str] | None = None,
) -> ReconcileSummary:
    """Diff watch list against active subs.

    By default reads ``living_profile.watch_for_tomorrow`` (the legacy
    morning-trigger field; usually shaped wrong for external search).
    Pass ``watches_override`` to supply a list of search-shaped strings
    instead - typically from ``watch_synth.derive_external_watches``.

    Creates rows for new watch lines (Exa provisioning is deferred to
    ``provision_pending_websets``). Deactivates rows whose intent_key no
    longer appears in the current watch list. Enforces ``max_active``
    via least-recently-refreshed eviction.

    Returns a ReconcileSummary; never raises.
    """
    async with async_session() as session:
        user = (
            await session.execute(
                select(User).where(User.id == user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            return ReconcileSummary(
                user_id=user_id,
                created=0,
                deactivated=0,
                skipped_over_budget=0,
            )

        profile = dict(user.living_profile or {})
        if watches_override is not None:
            watches = list(watches_override)
        else:
            watches = profile.get("watch_for_tomorrow") or []
            if isinstance(watches, str):
                watches = [watches]
        watch_lines = [str(w).strip() for w in watches if str(w).strip()]
        # Deterministic ordering: sort by intent_key so LRU eviction /
        # over-budget skipping is reproducible across CPython versions.
        wanted_pairs = sorted(
            ((intent_key_for_watch_line(w), w) for w in watch_lines),
            key=lambda kv: kv[0],
        )
        wanted_keys: dict[str, str] = {}
        for k, w in wanted_pairs:
            wanted_keys.setdefault(k, w)

        active_rows = list(
            (
                await session.execute(
                    select(ProactiveSubscription).where(
                        ProactiveSubscription.user_id == user_id,
                        ProactiveSubscription.active.is_(True),
                    )
                )
            ).scalars()
        )
        active_keys = {r.intent_key: r for r in active_rows}

        # Deactivate rows no longer in the watch list
        deactivated = 0
        for key, row in active_keys.items():
            if key not in wanted_keys:
                row.active = False
                row.last_refreshed_at = _utcnow_naive()
                deactivated += 1

        # Create rows for new watch lines, respecting the budget
        active_count_after_deact = sum(1 for r in active_rows if r.active)
        budget_remaining = max(0, int(max_active) - active_count_after_deact)
        created = 0
        skipped = 0
        for key, line in wanted_keys.items():
            if key in active_keys:
                continue
            if budget_remaining <= 0:
                skipped += 1
                continue
            row = ProactiveSubscription(
                user_id=user_id,
                intent_key=key,
                description=line[:1000],
                cadence="daily",
                created_at=_utcnow_naive(),
                last_refreshed_at=_utcnow_naive(),
                active=True,
            )
            session.add(row)
            created += 1
            budget_remaining -= 1

        await session.commit()

    return ReconcileSummary(
        user_id=user_id,
        created=created,
        deactivated=deactivated,
        skipped_over_budget=skipped,
    )


# ---------------------------------------------------------------------------
# provision (Exa)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvisionSummary:
    """Result of one ``provision_pending_websets`` pass."""

    user_id: str
    provisioned: int
    failed: int


async def provision_pending_websets(user_id: str) -> ProvisionSummary:
    """For each active subscription with webset_id IS NULL, create the
    Exa webset and attach a monitor. Persists the IDs back to the row.

    No-op when EXA_API_KEY is missing — the Exa client refuses to call.
    Failures are logged and counted; the row is left pending so the next
    reconcile pass retries.
    """
    if not have_exa_key():
        logger.info(
            "provision_pending_websets: no EXA_API_KEY, skipping user=%s",
            user_id[:8] if user_id else "?",
        )
        return ProvisionSummary(user_id, provisioned=0, failed=0)

    provisioned = 0
    failed = 0
    async with async_session() as session:
        # Pick up two states:
        #   1. webset_id IS NULL  -> needs both webset_create + monitor_create
        #   2. webset_id IS NOT NULL AND monitor_id IS NULL -> webset already
        #      created (e.g. on a prior pass that hit a rate limit during
        #      monitor_create); just retry the monitor.
        rows = list(
            (
                await session.execute(
                    select(ProactiveSubscription).where(
                        ProactiveSubscription.user_id == user_id,
                        ProactiveSubscription.active.is_(True),
                        ProactiveSubscription.monitor_id.is_(None),
                    )
                )
            ).scalars()
        )

        for idx, row in enumerate(rows):
            # Polite delay between iterations - Exa's Starter tier caps
            # concurrent /websets/v0/* operations (typically 1-3). Fast
            # back-to-back creates trip 403 "max concurrent requests"
            # and leave orphan websets behind.
            if idx > 0:
                await asyncio.sleep(_PROVISION_DELAY_S)

            webset_id: str | None = row.webset_id
            if webset_id is None:
                try:
                    webset = await exa_webset_create(row.description, count=10)
                    webset_id = str(webset.get("id") or "").strip() or None
                    if not webset_id:
                        raise RuntimeError("webset response missing id")
                except Exception:
                    logger.exception(
                        "provision_pending_websets: webset_create failed user=%s intent=%s",
                        user_id[:8] if user_id else "?",
                        row.intent_key,
                    )
                    failed += 1
                    continue

                # Persist webset_id IMMEDIATELY so a downstream monitor_create
                # failure doesn't leave the webset orphaned at Exa with no
                # local pointer. Next pass retries monitor only.
                row.webset_id = webset_id
                row.last_refreshed_at = _utcnow_naive()
                await session.flush()

            try:
                monitor_fields = _monitor_webhook_fields()
                monitor = await exa_monitor_create(
                    webset_id=webset_id,
                    cadence=row.cadence or "daily",
                    behavior="search",
                    fields=monitor_fields,
                )
                monitor_id_str = str(monitor.get("id") or "").strip() or None
                row.monitor_id = monitor_id_str
                row.last_refreshed_at = _utcnow_naive()
                provisioned += 1
            except Exception:
                logger.exception(
                    "provision_pending_websets: monitor_create failed user=%s intent=%s webset=%s",
                    user_id[:8] if user_id else "?",
                    row.intent_key,
                    webset_id,
                )
                failed += 1
                continue

        await session.commit()

    return ProvisionSummary(user_id, provisioned=provisioned, failed=failed)


# ---------------------------------------------------------------------------
# webhook write path
# ---------------------------------------------------------------------------


async def record_monitor_hit(payload: dict[str, Any]) -> int:
    """Process one Exa monitor webhook payload.

    Looks up the matching ``ProactiveSubscription`` by ``monitorId``,
    enqueues one ``ProactiveSignal`` per item, and bumps
    ``last_hit_at`` on the subscription. Returns the number of signals
    written. Drops payloads whose monitor isn't recognized — Exa may
    fire monitors created by orphaned subs after a row was deactivated.
    """
    monitor_id = str(payload.get("monitorId") or "").strip()
    items = payload.get("items") or []
    if not monitor_id or not isinstance(items, list):
        return 0

    async with async_session() as session:
        sub = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.monitor_id == monitor_id,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            return 0

        sub.last_hit_at = _utcnow_naive()
        await session.commit()
        sub_id = sub.id
        user_id = sub.user_id
        intent_key = sub.intent_key

    queue = SignalQueueRepo()
    written = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        await queue.enqueue(
            user_id=user_id,
            subscription_id=sub_id,
            intent_key=intent_key,
            payload=item,
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# derive + reconcile in one shot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeriveAndReconcileSummary:
    """Result of a derive + reconcile pass with the derived watches inline.

    Returned so callers (CLI, dashboards, manual smoke runs) can see what
    Donna actually decided to watch and why.
    """

    user_id: str
    derived_count: int
    reconcile: ReconcileSummary
    watches: list[Any]  # list[DerivedWatch] but kept loose to avoid circular import


async def derive_and_reconcile(
    user_id: str,
    *,
    max_active: int = 5,
) -> DeriveAndReconcileSummary:
    """Run the full fanout: Living Profile -> derived watches -> subs.

    This is the entry point a worker / cron should call. It:
      1. asks Haiku what to watch for THIS user RIGHT NOW (watch_synth)
      2. reconciles those into proactive_subscriptions rows
      3. returns the derived watches inline so the caller can log them
    """
    from backend.web.proactive.watch_synth import derive_external_watches

    derived = await derive_external_watches(user_id, max_watches=max_active)
    watch_strings = [w.description for w in derived]
    summary = await reconcile_subscriptions(
        user_id, max_active=max_active, watches_override=watch_strings
    )
    return DeriveAndReconcileSummary(
        user_id=user_id,
        derived_count=len(derived),
        reconcile=summary,
        watches=list(derived),
    )
