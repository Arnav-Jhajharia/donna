"""Proactive proposer: scan ambient signal → emit candidate intents.

A Proposer reads one kind of signal (calendar, chat, entity mentions) and
returns `CandidateIntent` records. Candidates are authored through the same
`run_attention_pipeline` and persisted as `status=SHADOW`, `origin=
SHADOW_INFERRED`. The shadow loop later decides whether to offer them.

Scope for v1: `CalendarRecurrenceProposer` is real (runs on live DB data
when available, falls back to the fixture). `ChatPhraseProposer` and
`EntityMentionProposer` are declared stubs — they return [] until the
underlying signal readers land. Wiring them up is additive.

Precision > recall. A noisy proposer ships offers the user will dismiss,
which burns trust. If unsure, emit nothing.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from donna.attention.dry_run import CalendarFetcher
from donna.attention.harness import run_attention_pipeline
from donna.attention.normalize import UserContext, load_user_timezone
from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionStatus,
    ShadowState,
)
from donna.attention.store import AttentionStore
from donna.attention.tools import _coerce_uuid
from donna.attention.vocabulary import SourceType

logger = logging.getLogger(__name__)


# -- Candidate shape ---------------------------------------------------------


@dataclass(frozen=True)
class CandidateIntent:
    """One proposed intent waiting to be authored."""

    raw_intent: str
    proposer: str
    rationale: str
    signal: dict[str, Any] = field(default_factory=dict)
    priority: str = "low"  # low | medium | high


class Proposer(Protocol):
    name: str

    def propose(self, user_id: str) -> list[CandidateIntent]: ...


# -- Calendar recurrence proposer --------------------------------------------


_STOPWORDS = {
    "the", "a", "an", "with", "at", "to", "and", "of", "for",
    "meeting", "call", "sync", "catchup", "catch-up", "standup",
}
_MIN_RECURRENCES = 2
_MAX_CANDIDATES_PER_PROPOSER = 5

# Titles that shouldn't trigger prep proposals even if recurring. These are
# personal routines or calendar blocks, not meetings the user wants briefed.
_ROUTINE_TITLE_TOKENS = frozenset({
    "gym", "workout", "run", "running", "yoga", "meditation",
    "lunch", "breakfast", "dinner", "coffee",
    "commute", "travel", "block", "focus", "deep work", "dnd",
    "ooo", "out of office", "vacation", "pto", "holiday",
})


def _is_routine(title_signature: str) -> bool:
    tokens = set(title_signature.split())
    return bool(tokens & _ROUTINE_TITLE_TOKENS)


def _normalize_title(title: str) -> str:
    """Collapse a calendar title to a comparable signature.

    "1:1 with Sarah" and "1:1 with Sarah - rescheduled" should collide.
    """
    t = title.lower().strip()
    # strip common suffixes that break recurrence detection
    for sep in (" - ", " — ", " / ", " | "):
        if sep in t:
            t = t.split(sep)[0].strip()
    tokens = [tok for tok in t.split() if tok not in _STOPWORDS]
    return " ".join(tokens) or t


class CalendarRecurrenceProposer:
    """Detect recurring calendar titles and propose `prep_doc` intents.

    Signal: an event title that appears ≥ _MIN_RECURRENCES times in the
    upcoming window. Recurring meetings tend to benefit from prep.
    """

    name = "calendar_recurrence"

    def __init__(self, fetcher: CalendarFetcher | None = None) -> None:
        self._fetcher = fetcher or CalendarFetcher()

    def propose(self, user_id: str) -> list[CandidateIntent]:
        # Synthesize a minimal Source so CalendarFetcher is happy.
        from donna.attention.schema import Source

        source = Source(
            type=SourceType.CALENDAR_EVENTS,
            params={"lookahead_days": 30},
        )
        events = self._fetcher.fetch(source, user_id)
        if not events:
            return []

        titles = [str(e.get("title", "")).strip() for e in events if e.get("title")]
        sigs = Counter(_normalize_title(t) for t in titles if t)

        candidates: list[CandidateIntent] = []
        for sig, count in sigs.most_common(_MAX_CANDIDATES_PER_PROPOSER):
            if count < _MIN_RECURRENCES or not sig:
                continue
            if _is_routine(sig):
                logger.debug("skip routine title %r", sig)
                continue
            # Grab a representative original title for the intent string.
            representative = next(
                (t for t in titles if _normalize_title(t) == sig), sig
            )
            candidates.append(
                CandidateIntent(
                    raw_intent=f"prep me 15 minutes before '{representative}'",
                    proposer=self.name,
                    rationale=(
                        f"'{representative}' recurs {count}x in the next 30 days; "
                        "recurring meetings usually benefit from prep."
                    ),
                    signal={"title_signature": sig, "recurrences": count},
                    priority="low",
                )
            )
        return candidates


# -- Stub proposers (explicit no-ops for now) --------------------------------


class ChatPhraseProposer:
    """TODO: scan recent chat for 'still waiting on X', 'remind me about Y'."""

    name = "chat_phrase"

    def propose(self, user_id: str) -> list[CandidateIntent]:
        return []


class EntityMentionProposer:
    """TODO: named entities the user references but has no attention for yet."""

    name = "entity_mention"

    def propose(self, user_id: str) -> list[CandidateIntent]:
        return []


# -- Aggregator --------------------------------------------------------------


_DEFAULT_PROPOSERS: tuple[Proposer, ...] = (
    CalendarRecurrenceProposer(),
    ChatPhraseProposer(),
    EntityMentionProposer(),
)


def propose_candidates(
    user_id: str,
    *,
    proposers: tuple[Proposer, ...] | None = None,
) -> list[CandidateIntent]:
    """Run all proposers and return combined candidates (dedup by raw_intent)."""
    proposers = proposers or _DEFAULT_PROPOSERS
    seen: set[str] = set()
    out: list[CandidateIntent] = []
    for p in proposers:
        try:
            for c in p.propose(user_id):
                key = c.raw_intent.lower().strip()
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
        except Exception:
            logger.exception("proposer %s failed", p.name)
    return out


# -- Shadow authoring --------------------------------------------------------


@dataclass(frozen=True)
class ShadowResult:
    candidate: CandidateIntent
    attention: Attention | None
    authored_via: str
    authored_confidence: float
    error: str | None = None


async def propose_and_shadow(
    user_id: str,
    *,
    proposers: tuple[Proposer, ...] | None = None,
    store: AttentionStore | None = None,
    existing_titles: set[str] | None = None,
) -> list[ShadowResult]:
    """Propose candidates, author each, persist as SHADOW.

    Skips a candidate if an attention with the same title already exists
    (prevents re-proposing what the user has already set up).
    """
    store = store or AttentionStore()
    if existing_titles is None:
        existing_titles = {a.spec.title.lower() for a in store.list()}

    candidates = propose_candidates(user_id, proposers=proposers)
    tz = await load_user_timezone(user_id)
    ctx = UserContext(user_id=user_id, user_tz=tz) if tz else UserContext(user_id=user_id)
    results: list[ShadowResult] = []

    for candidate in candidates:
        try:
            pipeline = await run_attention_pipeline(candidate.raw_intent, ctx)
        except Exception as e:
            logger.exception("shadow authoring failed for %r", candidate.raw_intent)
            results.append(
                ShadowResult(
                    candidate=candidate,
                    attention=None,
                    authored_via="error",
                    authored_confidence=0.0,
                    error=str(e),
                )
            )
            continue

        title = pipeline.authored.spec.title.lower()
        if title in existing_titles:
            logger.info("shadow candidate %r collides with existing; skipping", title)
            results.append(
                ShadowResult(
                    candidate=candidate,
                    attention=None,
                    authored_via=pipeline.authored.via,
                    authored_confidence=pipeline.authored.confidence,
                    error="duplicate_title",
                )
            )
            continue
        existing_titles.add(title)

        attention = Attention(
            user_id=_coerce_uuid(user_id),
            spec=pipeline.authored.spec,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=AttentionStatus.SHADOW,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState(priority=candidate.priority),
        )
        store.save(attention)
        results.append(
            ShadowResult(
                candidate=candidate,
                attention=attention,
                authored_via=pipeline.authored.via,
                authored_confidence=pipeline.authored.confidence,
            )
        )
    return results
