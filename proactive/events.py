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
    "system_b_web",          # NEW: System B web hits as a unified source
]

SpeechAct = Literal[
    "dont_forget",            # keeper — user opted in, never miss
    "heads_up",               # alert — world moved, situation changed
    "i_noticed",              # mirror — pattern reflected, soft register
    "now_the_moment",         # anticipator — time has arrived
    "thought_youd_want",      # curator — earn the interrupt
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
      speech_act  — register the message is delivered in. Defaults to
                    thought_youd_want for back-compat with existing call
                    sites. Source adapters set it explicitly post-Phase-1.
      payload     — the source-specific shape, normalized into a small
                    dict so the judge prompt can render it without
                    branching on type.
      signals     — Tier 1 deterministic output (score + signal labels).
                    Kept as ``dict[str, Any]`` so non-email scorers can
                    drop in their own keys without forcing a schema bump.

                    Well-known optional keys (set by source adapters when
                    applicable; absent otherwise):
                      event_age_minutes (float)
                        Minutes elapsed since the underlying event happened
                        (e.g. email arrival, calendar change, monitor hit).
                        Used by ``proactive.fresh_signal.should_prefetch`` to
                        decide whether to re-fetch source state at Tier 3
                        context build. When missing, the pre-fetch is
                        skipped (safe default).
                      is_urgent_signal (bool)
                        True when the source-specific scorer judged this
                        event time-sensitive enough to upgrade the speech
                        act from thought_youd_want to heads_up. Used by
                        ``proactive.sources._inference.infer_speech_act``.
                      score (float)
                        Per-source relevance score from the Tier 1 scorer.
                        Currently used by the email path; other sources may
                        populate it analogously.
    """

    user_id: str
    source: ProactiveSource
    source_ref: str
    topic_key: str
    # speech_act defaults to thought_youd_want for back-compat with existing
    # call sites. Source adapters set it explicitly post-Phase-1.
    speech_act: SpeechAct = "thought_youd_want"
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
