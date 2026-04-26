"""Attention-offer source adapter for the unified proactive pipeline.

A shadow attention that promotes to ``OFFERED`` is currently surfaced
passively (rendered into the next reactive turn's context block). Phase 3
makes the path optional-active: when ``DONNA_PROACTIVE_TIERED=1`` AND
``DONNA_PROACTIVE_OFFER_ACTIVE=1`` are both set, the promoter dispatches a
``ProactiveEvent`` so Tier 2 can decide whether to ping (active push),
hold (passive surfacing keeps working), or drop (rare; Tier 2 thinks the
offer is stale).

The adapter never reaches outside the in-memory ``Attention``. The
promoter passes a freshly saved Attention; we extract the bits the judge
needs and stop there.
"""
from __future__ import annotations

import logging
from typing import Any

from proactive.events import ProactiveEvent

logger = logging.getLogger(__name__)


_RATIONALE_LIMIT = 400


def _spec_value(attention: Any, *path: str) -> Any:
    """Walk ``attention.spec.*`` defensively. Empty string on any miss."""
    cur: Any = getattr(attention, "spec", None)
    for part in path:
        if cur is None:
            return ""
        cur = getattr(cur, part, None)
    return cur


def make_event(attention: Any) -> ProactiveEvent:
    """Build a ``ProactiveEvent`` for an attention that promoted to OFFERED.

    ``source_ref`` and ``topic_key`` both equal ``str(attention.id)`` so a
    re-promotion (extremely unlikely) would dedup on the same topic and
    not double-fire.
    """
    title = str(_spec_value(attention, "title") or "")
    card_attr = _spec_value(attention, "card")
    card_value = str(getattr(card_attr, "value", card_attr) or "") if card_attr else ""
    subject_name = str(_spec_value(attention, "subject", "name") or "")
    description = str(_spec_value(attention, "description") or "").strip()
    if len(description) > _RATIONALE_LIMIT:
        description = description[:_RATIONALE_LIMIT] + " ..."

    payload: dict[str, Any] = {
        "title": title,
        "card": card_value,
        "subject": subject_name,
        "rationale": description,
    }

    shadow = getattr(attention, "shadow_state", None)
    promotion_hits = int(getattr(shadow, "promotion_hits", 0) or 0)
    tick_count = int(getattr(shadow, "tick_count", 0) or 0)

    signals: dict[str, Any] = {
        "promotion_hits": promotion_hits,
        "tick_count": tick_count,
    }

    aid = str(getattr(attention, "id", "") or "")
    user_id = str(getattr(attention, "user_id", "") or "")
    return ProactiveEvent(
        user_id=user_id,
        source="attention_offer",
        source_ref=aid,
        topic_key=aid,
        payload=payload,
        signals=signals,
    )


def attach_recent_source_counts(
    event: ProactiveEvent, source_counts: dict[str, int] | None
) -> ProactiveEvent:
    """Return a new event with ``source_counts`` woven into ``signals``.

    The promoter has the latest dry-run preview's ``source_counts`` in
    hand. We pass them in via this helper rather than re-reading the
    attention store from inside the adapter.
    """
    if not source_counts:
        return event
    signals = dict(event.signals)
    signals["source_counts"] = dict(source_counts)
    return ProactiveEvent(
        user_id=event.user_id,
        source=event.source,
        source_ref=event.source_ref,
        topic_key=event.topic_key,
        payload=dict(event.payload),
        signals=signals,
    )
