"""Reflex layer — the cheap, fast, model-free part of donna's voice.

Two stages, both run on every Deepgram interim transcript:

1. **Regex match** on the partial text. If a known pattern hits, emit
   the corresponding canned filler immediately (<10ms).
2. **Rhythm heuristic** if no regex match. Looks at speech timing:
   pauses, continuous speech duration, pace shift. Decides whether to
   emit a backchannel (`mm` mixed at -18dB while user is still talking)
   or a filler (`[breath] mhm` on pause-after-3-words).

If both miss and a pause is detected, the caller can escalate to
SparkBrain (Groq Llama-3.1-8B) for a novel reflex. Reflex+Spark+Brain
form three layers of decreasing speed and increasing intelligence.

Output is always one of:
- `FillerCue(tag="mm", mode="filler")` — plays in the gap, full volume.
- `FillerCue(tag="mm", mode="backchannel")` — mixed at -18dB while user
  is still talking, like a real human "mm-hm".
- `None` — no reflex this tick. The caller may try Spark or do nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


FillerMode = Literal["filler", "backchannel"]


@dataclass(frozen=True)
class FillerCue:
    """One reflex emission. tag is the filler text (with optional audio
    tags), mode decides how it's mixed into the outbound audio."""

    tag: str
    mode: FillerMode
    source: str  # "regex" | "rhythm" | "spark" — useful for tracing


# ─────────────────────── Layer 1: regex map ───────────────────────────
#
# Order matters: more specific patterns first. Each pattern is matched
# against the *tail* of the partial transcript (last ~60 chars), so
# "i'm so tired you know" hits the "you know" rule even though "i'm so"
# would also match earlier in the same string.
#
# Keep the response set tight. Six fillers max. Variety is good but
# repetition is part of how humans actually sound — say "mm" five times
# in a row sounds more natural than rotating through six unique tokens.

_REGEX_RULES: tuple[tuple[re.Pattern[str], str, FillerMode], ...] = (
    # Closing-the-thought hooks: user is wrapping up, lean in.
    (re.compile(r"\byou know\??\s*$", re.IGNORECASE), "yeah", "filler"),
    (re.compile(r"\bright\??\s*$", re.IGNORECASE), "mhm", "filler"),
    # Self-correction / hesitation: bridge with a soft prompt.
    (re.compile(r"\bwait wait\b", re.IGNORECASE), "[laughs softly] yeah", "filler"),
    (re.compile(r"\bi mean\b", re.IGNORECASE), "mhm", "backchannel"),
    (re.compile(r"\b(uh+|um+)\b", re.IGNORECASE), "mm", "backchannel"),
    # Emotional flags: respond with softness, never closure.
    (re.compile(r"\bi can'?t believe\b", re.IGNORECASE), "[breath] mm", "filler"),
    (re.compile(r"\bi'?m so\b", re.IGNORECASE), "[softly] yeah", "backchannel"),
    (re.compile(r"\bhonestly\b", re.IGNORECASE), "mhm", "backchannel"),
    # Story-mode: user is narrating, keep them going.
    (re.compile(r"\b(so basically|like|and then)\b", re.IGNORECASE), "mhm", "backchannel"),
    # Question-shaped tail: lean in, don't fill — silence is the right answer.
    # We return a sentinel that the caller treats as "say nothing intentionally".
)


def regex_match(partial_transcript: str) -> FillerCue | None:
    """Return a canned filler if the tail of the transcript matches a
    rule. None means no rule fired — caller may try rhythm/spark."""
    if not partial_transcript:
        return None
    tail = partial_transcript[-80:]
    for pattern, tag, mode in _REGEX_RULES:
        if pattern.search(tail):
            return FillerCue(tag=tag, mode=mode, source="regex")
    return None


# ─────────────────────── Layer 2: rhythm heuristics ───────────────────


@dataclass
class RhythmState:
    """Per-turn rolling state. Reset on user-utterance-finalized."""

    last_partial: str = ""
    last_partial_at: float = 0.0
    turn_started_at: float | None = None
    backchannel_emitted_at: float = 0.0
    filler_emitted_at: float = 0.0

    def reset_for_new_turn(self, now_s: float) -> None:
        self.last_partial = ""
        self.last_partial_at = now_s
        self.turn_started_at = now_s
        self.backchannel_emitted_at = 0.0
        self.filler_emitted_at = 0.0


@dataclass
class RhythmRouter:
    """Emit fillers/backchannels based on speech timing.

    Tunables match the audit numbers in DESIGN.md — backchannel cooldown
    3.5s, pause threshold 150ms, continuous-talk threshold 4s.
    """

    pause_threshold_s: float = 0.15
    continuous_talk_threshold_s: float = 4.0
    backchannel_cooldown_s: float = 3.5
    filler_cooldown_s: float = 1.5
    min_words_for_filler: int = 3

    def step(
        self,
        partial_transcript: str,
        now_s: float,
        state: RhythmState,
    ) -> FillerCue | None:
        if state.turn_started_at is None:
            state.turn_started_at = now_s

        text = (partial_transcript or "").strip()
        words = text.split()

        # Empty / short partials: just track.
        if len(words) < self.min_words_for_filler:
            state.last_partial = text
            state.last_partial_at = now_s
            return None

        partial_changed = text != state.last_partial

        # Rule A: pause-after-meaningful-content → emit a filler (sounds
        # like donna grabbing a thought before they finish).
        filler_off_cooldown = (
            state.filler_emitted_at == 0.0
            or now_s - state.filler_emitted_at >= self.filler_cooldown_s
        )
        if (
            not partial_changed
            and now_s - state.last_partial_at >= self.pause_threshold_s
            and filler_off_cooldown
        ):
            state.filler_emitted_at = now_s
            return FillerCue(tag="[breath] mhm", mode="filler", source="rhythm")

        # Rule B: long continuous talk → drop a low-vol backchannel
        # *while the user is still talking*. -18dB mix happens upstream;
        # we just mark mode="backchannel".
        elapsed = now_s - state.turn_started_at
        backchannel_off_cooldown = (
            state.backchannel_emitted_at == 0.0
            or now_s - state.backchannel_emitted_at >= self.backchannel_cooldown_s
        )
        if elapsed >= self.continuous_talk_threshold_s and backchannel_off_cooldown:
            state.backchannel_emitted_at = now_s
            state.last_partial = text
            state.last_partial_at = now_s
            return FillerCue(tag="mm", mode="backchannel", source="rhythm")

        if partial_changed:
            state.last_partial = text
            state.last_partial_at = now_s
        return None


# ─────────────────────── Composite router ─────────────────────────────


@dataclass
class ReflexRouter:
    """Glue: try regex first, then rhythm. Spark is wired by the caller
    as a third fallback when both miss and a pause has been detected."""

    rhythm: RhythmRouter = field(default_factory=RhythmRouter)
    state: RhythmState = field(default_factory=RhythmState)

    def reset_for_new_turn(self, now_s: float) -> None:
        self.state.reset_for_new_turn(now_s)

    def step(self, partial_transcript: str, now_s: float) -> FillerCue | None:
        regex_hit = regex_match(partial_transcript)
        if regex_hit is not None:
            # Cooldown bookkeeping so rhythm doesn't double-fire next tick.
            if regex_hit.mode == "filler":
                self.state.filler_emitted_at = now_s
            else:
                self.state.backchannel_emitted_at = now_s
            return regex_hit
        return self.rhythm.step(partial_transcript, now_s, self.state)
