"""SparkBrain — donna's reflex.

Listens to Deepgram interim transcripts. On a brief pause after the
user has said at least 3 words, fires a tiny model (Groq Llama-3.1-8B
by default) for a 1-5 word filler that bridges silence while the real
brain cooks.

Strict output discipline:
- 1-5 words.
- No opinions, no interpretation, no closure.
- Lowercase. Audio tags optional.
- Never generates anything that commits the conversation to a stance,
  because the real reply might disagree with that stance.

Allowed shape: "mm" / "oh wait" / "yeah tell me" / "[breath] mhm" /
"wait wait" / "[laughs softly] ok" / "hmm".

Banned shape: anything with adjectives, verbs that imply judgment,
or content beyond acknowledgment.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)


_REFLEX_SYSTEM = (
    "you are donna's reflex on a phone call. you hear the first few "
    "words of what someone is saying. emit a 1-5 word acknowledgment "
    "that bridges silence while the real reply is being prepared.\n\n"
    "rules:\n"
    "- 1 to 5 words. count them.\n"
    "- lowercase only.\n"
    "- never commit to an opinion. never interpret. never close a topic.\n"
    "- audio tags allowed inline: [breath] [softly] [laughs softly].\n"
    "- if unsure, output 'mm'.\n\n"
    "good outputs:\n"
    "  mm\n"
    "  oh wait\n"
    "  yeah tell me\n"
    "  wait wait\n"
    "  [breath] mhm\n"
    "  [laughs softly] ok\n"
    "  hmm go on\n\n"
    "bad outputs (never produce these):\n"
    "  yeah that's rough\n"
    "  oh no I'm sorry\n"
    "  that makes sense\n"
    "  totally agree\n"
    "  I think you should\n\n"
    "output ONLY the filler. no explanation. no quotes."
)


_BANNED_TOKENS = {
    "agree",
    "disagree",
    "should",
    "must",
    "think",
    "believe",
    "sorry",
    "rough",
    "sense",
    "totally",
    "definitely",
    "absolutely",
    "right",
    "wrong",
    "good",
    "bad",
    "smart",
    "stupid",
    "love",
    "hate",
}


_DEFAULT_FALLBACKS = ("mm", "[breath] mhm", "oh wait", "yeah tell me", "hmm")


def _is_safe(text: str) -> bool:
    """Reject filler that violates the discipline."""
    if not text:
        return False
    stripped = re.sub(r"\[[^\]]+\]", "", text).strip()
    words = [w for w in re.findall(r"[a-z']+", stripped.lower())]
    if not words or len(words) > 5:
        return False
    if any(w in _BANNED_TOKENS for w in words):
        return False
    return True


class SparkClient(Protocol):
    """Anything that can turn a partial-transcript into a 1-5 word filler."""

    async def react(self, partial_transcript: str) -> str: ...


@dataclass
class GroqSpark:
    """Groq Llama-3.1-8B-instant. ~50ms TTFT, near-free, ideal for reflex."""

    api_key: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    model: str = "llama-3.1-8b-instant"
    timeout_s: float = 1.5
    _fallback_idx: int = 0

    async def react(self, partial_transcript: str) -> str:
        partial = (partial_transcript or "").strip()
        if not partial or not self.api_key:
            return self._fallback()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": _REFLEX_SYSTEM},
                            {
                                "role": "user",
                                "content": f"user is saying: {partial}",
                            },
                        ],
                        "max_tokens": 16,
                        "temperature": 0.6,
                        "stop": ["\n", "."],
                    },
                )
            if resp.status_code != 200:
                log.warning("spark: groq %s %s", resp.status_code, resp.text[:200])
                return self._fallback()
            data = resp.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .lower()
            )
            if _is_safe(text):
                return text
            log.info("spark: rejected unsafe filler %r → fallback", text)
            return self._fallback()
        except Exception as e:
            log.warning("spark: groq error %s", e)
            return self._fallback()

    def _fallback(self) -> str:
        chosen = _DEFAULT_FALLBACKS[self._fallback_idx % len(_DEFAULT_FALLBACKS)]
        self._fallback_idx += 1
        return chosen


@dataclass
class StubSpark:
    """Deterministic spark for tests. Always returns rotating fallbacks."""

    _idx: int = 0

    async def react(self, partial_transcript: str) -> str:
        chosen = _DEFAULT_FALLBACKS[self._idx % len(_DEFAULT_FALLBACKS)]
        self._idx += 1
        return chosen


@dataclass
class SparkController:
    """Decides *when* to fire spark, given the stream of partial transcripts.

    Heuristic: fire on a brief pause (≥150ms) after the user has spoken
    at least 3 words in the current utterance, but only once per turn.
    """

    spark: SparkClient
    min_words: int = 3
    pause_threshold_s: float = 0.15
    _fired_for_turn: bool = False
    _last_partial: str = ""
    _last_partial_at: float = 0.0

    def reset_for_new_turn(self) -> None:
        self._fired_for_turn = False
        self._last_partial = ""
        self._last_partial_at = 0.0

    async def maybe_fire(self, partial_transcript: str, now_s: float) -> str | None:
        if self._fired_for_turn:
            return None
        words = partial_transcript.strip().split()
        if len(words) < self.min_words:
            self._last_partial = partial_transcript
            self._last_partial_at = now_s
            return None
        # Pause check: same partial seen >= pause_threshold ago = pause hit.
        if (
            partial_transcript == self._last_partial
            and now_s - self._last_partial_at >= self.pause_threshold_s
        ):
            self._fired_for_turn = True
            return await self.spark.react(partial_transcript)
        if partial_transcript != self._last_partial:
            self._last_partial = partial_transcript
            self._last_partial_at = now_s
        return None
