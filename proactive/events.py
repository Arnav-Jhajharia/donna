"""Canonical ``ProactiveEvent`` envelope.

Every proactive trigger (email, attention fire, attention offer, calendar)
normalizes into this shape before reaching the dispatcher. Source-specific
adapters live in ``proactive/sources/`` and produce events from native
trigger payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Sources we know about today. Extend as adapters land. Kept narrow on
# purpose so dispatcher / judge prompts can reason about per-source rules.
ProactiveSource = Literal[
    "email",
    "attention_fire",
    "attention_offer",
    "calendar",
    "pattern",
]


@dataclass(frozen=True)
class ProactiveEvent:
    """Source-agnostic envelope for the proactive pipeline.

    Fields:
      user_id     — Donna user id (string FK on users.id).
      source      — narrow vocabulary, see ``ProactiveSource``.
      source_ref  — native id (gmail_message_id, attention_id, event_id...).
      topic_key   — dedup key. For email use thread_id (so a long thread
                    does not re-fire). Defaults to source_ref when the
                    adapter has no better grouping.
      payload     — the source-specific shape, normalized into a small
                    dict so the judge prompt can render it without
                    branching on type.
      signals     — Tier 1 deterministic output (score + signal labels).
                    Kept as ``dict[str, Any]`` so non-email scorers can
                    drop in their own keys without forcing a schema bump.
    """

    user_id: str
    source: ProactiveSource
    source_ref: str
    topic_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)


# -- Source adapters ---------------------------------------------------------
#
# Adapters import lazily inside their helpers so importing the events module
# does not drag in Composio / attention internals that may not be needed for
# every consumer (tests, telemetry, etc.).


def make_event_from_email(
    user_id: str,
    msg: Any,
    score: Any,
) -> ProactiveEvent:
    """Build a ``ProactiveEvent`` from a normalized gmail message + score.

    ``msg`` is ``backend.integrations.composio_client.NormalizedGmailMessage``
    and ``score`` is ``backend.integrations.email_importance.ScoreResult``.
    Both are accepted as ``Any`` to keep the events module dependency-free.
    """
    body_excerpt = (
        getattr(msg, "body_text", None)
        or getattr(msg, "snippet", None)
        or ""
    )[:600]
    payload: dict[str, Any] = {
        "from_address": getattr(msg, "from_address", "") or "",
        "from_name": getattr(msg, "from_name", "") or "",
        "subject": getattr(msg, "subject", "") or "",
        "body_excerpt": body_excerpt,
    }
    signals: dict[str, Any] = {
        "score": float(getattr(score, "score", 0.0) or 0.0),
        "signals": list(getattr(score, "signals", []) or []),
    }
    thread_id = getattr(msg, "thread_id", None)
    gmail_message_id = getattr(msg, "gmail_message_id", "") or ""
    return ProactiveEvent(
        user_id=user_id,
        source="email",
        source_ref=gmail_message_id,
        topic_key=str(thread_id or gmail_message_id),
        payload=payload,
        signals=signals,
    )
