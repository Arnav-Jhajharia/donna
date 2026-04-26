"""Deterministic detection of explicit voice-message requests.

Both the per-turn runtime context (`context_builder.render_turn_context`) and
the PreToolUse hook (`hooks.pre_tool_hook`) need the same answer to the same
question: did the user explicitly ask for a voice reply this turn?

Substring match on lowercased input. False positives are cheap (one extra
context line + a marker the model would have wanted anyway). False negatives
are the failure mode that forced this whole module to exist.
"""
from __future__ import annotations


VOICE_REQUEST_PATTERNS: tuple[str, ...] = (
    "voice me", "voice it", "voice that", "voice this",
    "send me a voice", "send me voice", "send a voice",
    "send me a vm", "send a vm", "send me vm",
    "voice message", "voice memo", "voice note",
    "say it out loud", "say it aloud", "talk to me",
    "audio message", "audio reply", "in audio",
)


def detect_voice_request(text: str | None) -> bool:
    """True iff `text` contains any explicit voice-request phrasing.

    Case-insensitive substring match. Empty / None returns False.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(p in lowered for p in VOICE_REQUEST_PATTERNS)
