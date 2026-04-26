"""Decide whether to enable extended thinking for a given turn.

Thinking helps when the model must reason across ambiguity, orchestrate
multiple tool calls, or calibrate tone on sensitive topics. It hurts on
ambient chatter (adds latency + cost for no signal lift).

Heuristic is deliberately simple and inspectable. Tune by editing the
keyword lists, not by adding branches.
"""
from __future__ import annotations

from typing import Any

_AMBIENT_MAX_CHARS = 25

_DECISION_KEYWORDS = frozenset(
    {
        "should",
        "vs",
        "which",
        "compare",
        "pick",
        "decide",
        "help me",
        "worth it",
        "better",
        "best",
        "advice",
        "think about",
        "thoughts on",
        "plan",
        "strategy",
    }
)

_SAFETY_KEYWORDS = frozenset(
    {
        "kill myself",
        "suicid",
        "self harm",
        "self-harm",
        "end it",
        "want to die",
        "hurt myself",
        "overdose",
    }
)

_SUBSTANTIVE_QUESTION_MIN_CHARS = 40


def should_think(message: str, state: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Return (enable_thinking, reason) for this turn.

    `state` is the same dict passed to render_turn_context — we peek at
    reply context and first-message flag.
    """
    state = state or {}
    text = (message or "").strip()
    lower = text.lower()

    if not text:
        return (False, "empty")

    if any(k in lower for k in _SAFETY_KEYWORDS):
        return (True, "safety: calibration matters")

    if any(k in lower for k in _DECISION_KEYWORDS):
        return (True, "decision / comparison")

    if (state.get("reply_to_content") or "").strip():
        return (True, "replying to prior content")

    if isinstance(state.get("url_contents"), list) and state.get("url_contents"):
        return (True, "fetched url content present")

    if len(text) < _AMBIENT_MAX_CHARS and "?" not in text:
        return (False, "ambient chatter")

    if "?" in text and len(text) >= _SUBSTANTIVE_QUESTION_MIN_CHARS:
        return (True, "substantive question")

    if state.get("_is_first_message") and len(text) > 30:
        return (True, "first message, nontrivial")

    return (False, "default: no thinking needed")
