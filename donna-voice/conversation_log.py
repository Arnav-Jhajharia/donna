"""ConversationLog — single source of truth for what's been said on a call.

Both donnas (reflex layer + brain layer) and the user all append here.
Reflex reads the log to check what brain just said (avoid tone clash).
Brain reads the log to check what reflex recently emitted (avoid
repetition). The WhatsApp sync filters out `synthetic` entries so the
user's chat history doesn't fill up with "mm" and "[breath] mhm".

Entries are immutable. The log itself owns the list and only appends —
never edits, never deletes. Per-call instance; no cross-call state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

Speaker = Literal["user", "reflex", "brain"]


@dataclass(frozen=True)
class LogEntry:
    """One thing said on the call. Immutable."""

    speaker: Speaker
    text: str
    at: datetime
    synthetic: bool = False  # True for reflex fillers — skipped by WA sync.
    source: str | None = None  # "regex" | "rhythm" | "spark" | "donna_brain"


@dataclass
class ConversationLog:
    """Append-only ordered log of one call's utterances."""

    entries: list[LogEntry] = field(default_factory=list)

    # ─── append helpers (per speaker) ──────────────────────────────────

    def append_user(self, text: str, at: datetime | None = None) -> LogEntry:
        e = LogEntry(
            speaker="user",
            text=text,
            at=at or datetime.now(timezone.utc),
        )
        self.entries.append(e)
        return e

    def append_brain(self, text: str, at: datetime | None = None) -> LogEntry:
        e = LogEntry(
            speaker="brain",
            text=text,
            at=at or datetime.now(timezone.utc),
            source="donna_brain",
        )
        self.entries.append(e)
        return e

    def append_reflex(
        self,
        text: str,
        source: str,
        at: datetime | None = None,
    ) -> LogEntry:
        """Reflex utterances are always synthetic — they're what donna
        emits to bridge silence, not substantive content. WhatsApp sync
        filters them out."""
        e = LogEntry(
            speaker="reflex",
            text=text,
            at=at or datetime.now(timezone.utc),
            synthetic=True,
            source=source,
        )
        self.entries.append(e)
        return e

    # ─── reads (for cross-donna coherence) ──────────────────────────────

    def last_brain_reply(self) -> LogEntry | None:
        for e in reversed(self.entries):
            if e.speaker == "brain":
                return e
        return None

    def last_user_utterance(self) -> LogEntry | None:
        for e in reversed(self.entries):
            if e.speaker == "user":
                return e
        return None

    def recent_reflex_tags(self, n: int = 5) -> tuple[str, ...]:
        """The last N reflex fillers. Brain reads this to avoid repeating
        what reflex already said."""
        recent: list[str] = []
        for e in reversed(self.entries):
            if e.speaker == "reflex":
                recent.append(e.text)
            if len(recent) >= n:
                break
        return tuple(reversed(recent))

    def turns_since(self, speaker: Speaker, sentinel_index: int) -> int:
        """How many entries from `speaker` have appended since
        `sentinel_index`. Useful for cooldown logic."""
        return sum(
            1
            for e in self.entries[sentinel_index:]
            if e.speaker == speaker
        )

    # ─── exports (for WhatsApp + other surfaces) ────────────────────────

    def for_whatsapp(self) -> list[LogEntry]:
        """Only non-synthetic entries — the user's WhatsApp transcript
        should not contain reflex fillers."""
        return [e for e in self.entries if not e.synthetic]

    def for_brain_context(self, max_turns: int = 8) -> list[tuple[str, str]]:
        """Recent (role, text) tuples for the brain's chat-history
        prompt. Reflex fillers ARE included so the brain knows what
        donna already said this turn — but with role='assistant'."""
        out: list[tuple[str, str]] = []
        for e in self.entries[-max_turns * 2 :]:
            role = "user" if e.speaker == "user" else "assistant"
            out.append((role, e.text))
        return out
