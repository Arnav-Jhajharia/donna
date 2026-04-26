"""Attention-fire source adapter for the unified proactive pipeline.

The schedule worker drains ``DonnaSchedule`` rows that have an
``attention_id``. Phase 3 routes those fires through the dispatcher: this
adapter converts the row + (best-effort) hydrated ``Attention`` into a
``ProactiveEvent`` so the Tier 2 judge sees the same envelope shape every
other source produces.

The adapter is deliberately tolerant of a missing ``Attention``. If the
attention store is unreachable at fire time we still hand the dispatcher
an event built from the schedule row alone — the brain has enough context
from ``recurrence_meta`` to decide ship / hold / drop.
"""
from __future__ import annotations

import logging
from typing import Any

from proactive.events import ProactiveEvent

logger = logging.getLogger(__name__)


_RATIONALE_LIMIT = 400


def _spec_subject_name(attention: Any) -> str:
    """Pull ``spec.subject.name`` from a hydrated Attention. Empty on miss."""
    try:
        spec = getattr(attention, "spec", None)
        subject = getattr(spec, "subject", None) if spec is not None else None
        return str(getattr(subject, "name", "") or "")
    except Exception:
        logger.exception("attention_fire source: subject extraction failed")
        return ""


def _spec_card_value(attention: Any) -> str:
    """Pull ``spec.card.value`` from a hydrated Attention. Empty on miss."""
    try:
        spec = getattr(attention, "spec", None)
        card = getattr(spec, "card", None) if spec is not None else None
        # CardType is a str enum — fall back to str() if .value missing.
        return str(getattr(card, "value", card) or "")
    except Exception:
        logger.exception("attention_fire source: card extraction failed")
        return ""


def _spec_rationale(attention: Any) -> str:
    """Cap the spec description so the prompt budget stays bounded."""
    try:
        spec = getattr(attention, "spec", None)
        description = (
            getattr(spec, "description", "") if spec is not None else ""
        )
        text = str(description or "").strip()
        if len(text) > _RATIONALE_LIMIT:
            return text[:_RATIONALE_LIMIT] + " ..."
        return text
    except Exception:
        logger.exception("attention_fire source: rationale extraction failed")
        return ""


def make_event(row: Any, attention: Any | None) -> ProactiveEvent:
    """Build a ``ProactiveEvent`` for a fired attention reminder.

    ``row`` is the ``DonnaSchedule`` row that just fell due. ``attention``
    is the linked ``Attention`` if hydratable; ``None`` is acceptable and
    only thins out the optional payload fields.

    ``source_ref`` and ``topic_key`` both equal ``row.attention_id`` so the
    arbiter can apply per-topic cooldowns across recurring fires.
    """
    meta = getattr(row, "recurrence_meta", None) or {}
    if not isinstance(meta, dict):
        meta = {}

    question = str(meta.get("question") or "").strip()
    cadence_type = str(meta.get("cadence_type") or "one_shot").strip()
    fire_at = getattr(row, "fire_at", None)
    fire_at_iso = fire_at.isoformat() if fire_at is not None else "unknown"

    is_recurring = cadence_type == "scheduled"

    payload: dict[str, Any] = {
        "question": question,
        "cadence_type": cadence_type,
        "fire_at_iso": fire_at_iso,
    }
    subject_name = _spec_subject_name(attention) if attention is not None else ""
    card_value = _spec_card_value(attention) if attention is not None else ""
    rationale = _spec_rationale(attention) if attention is not None else ""
    if subject_name:
        payload["subject"] = subject_name
    if card_value:
        payload["card"] = card_value
    if rationale:
        payload["rationale"] = rationale

    signals: dict[str, Any] = {
        "cadence_type": cadence_type,
        "is_recurring": is_recurring,
    }

    attention_id = str(getattr(row, "attention_id", "") or "")
    user_id = str(getattr(row, "user_id", "") or "")
    return ProactiveEvent(
        user_id=user_id,
        source="attention_fire",
        source_ref=attention_id,
        topic_key=attention_id,
        payload=payload,
        signals=signals,
    )
