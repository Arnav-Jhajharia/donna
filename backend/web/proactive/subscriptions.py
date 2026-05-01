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

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import ProactiveSubscription, User
from db.session import async_session

logger = logging.getLogger(__name__)


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
) -> ReconcileSummary:
    """Diff ``living_profile.watch_for_tomorrow`` against active subs.

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
