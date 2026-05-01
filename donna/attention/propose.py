"""Proactive proposer: scan ambient signal → emit candidate intents.

A Proposer reads one kind of signal (calendar, chat, entity mentions) and
returns `CandidateIntent` records. Candidates are authored through the same
`run_attention_pipeline` and persisted as `status=SHADOW`, `origin=
SHADOW_INFERRED`. The shadow loop later decides whether to offer them.

Scope for v1: `CalendarRecurrenceProposer` is real. `ChatPhraseProposer`
fires the canonical "drinking signal -> next-day hydration tracker" loop
the user described. `EntityMentionProposer` is still a stub.

Precision > recall. A noisy proposer ships offers the user will dismiss,
which burns trust. If unsure, emit nothing.
"""
from __future__ import annotations

import inspect
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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


_DRINKING_PATTERN = re.compile(
    r"\b("
    # specific drinking phrasings (not bare "drinking water")
    r"drank\s+(?:way\s+)?too\s+much"
    r"|drank\s+(?:a\s+)?lot"
    r"|drinking\s+last\s+night"
    r"|drinking\s+(?:way\s+)?too\s+much"
    r"|too\s+much\s+to\s+drink"
    r"|too\s+much\s+last\s+night"
    r"|too\s+much\s+yesterday"
    r"|ended\s+up\s+drinking"
    # hangover-shaped tokens
    r"|wasted|hungover|hangover|hammered|smashed|blackout"
    # morning-after texture
    r"|rough\s+morning"
    r"|rough\s+night"
    r"|feel(?:ing)?\s+like\s+(?:trash|shit|garbage)"
    r"|head\s+is\s+pounding"
    r")\b",
    re.IGNORECASE,
)

# Subject tokens that mean "this is the hydration thread" — any existing
# attention whose subject or title contains one of these is treated as
# evidence the user already has hydration in flight, so we don't propose
# again.
_HYDRATION_TOKENS = ("hydration", "hydrate", "water intake", "water tracker")

# Lookback for the chat scan. Mirrors the "next morning after drinking"
# story arc — late-night hit at T should fire the proposer when it next
# ticks, well within 24h. Wider windows risk re-firing day after day.
_CHAT_LOOKBACK_HOURS = 24


class ChatPhraseProposer:
    """Propose a one-day hydration tracker after a drinking signal.

    Reads the last ``_CHAT_LOOKBACK_HOURS`` of chat for the user. When a
    drinking phrase fires (regex above) AND no existing hydration
    attention is in flight (SHADOW/OFFERED/LIVE), we emit one
    CandidateIntent. The downstream pipeline authors it as a TALLY
    attention, the shadow→offer loop graduates it, the dashboard
    composer renders it as a ``tracker-starter`` card.

    Single emission per call. We rely on the existing title-dedup in
    ``propose_and_shadow`` to keep us from re-shadowing the same intent
    on subsequent ticks once the SHADOW row exists.
    """

    name = "chat_phrase"

    def __init__(
        self,
        chat_fetcher: "Callable[[str, int], list[Any]] | None" = None,
        store: "AttentionStore | None" = None,
    ) -> None:
        # Injection points kept tiny: tests stub the chat fetch + store.
        # ``chat_fetcher`` may be sync (returns list) or async (returns
        # awaitable) — ``_fetch_recent_chat`` handles both.
        self._chat_fetcher = chat_fetcher
        self._store = store

    async def propose(self, user_id: str) -> list[CandidateIntent]:
        messages = await self._fetch_recent_chat(user_id, _CHAT_LOOKBACK_HOURS)
        if not messages:
            return []

        match = _first_drinking_hit(messages)
        if match is None:
            return []

        if self._user_already_has_hydration_attention(user_id):
            logger.debug(
                "chat_phrase: hydration attention already exists for user=%s; skipping",
                user_id[:8] if user_id else "?",
            )
            return []

        signal_excerpt = match["text"][:140]
        return [
            CandidateIntent(
                raw_intent=(
                    "set up a one-day hydration tracker for today: count glasses of "
                    "water toward a 2L target, surface progress on the dashboard. "
                    "this is a TALLY card with subject 'hydration'."
                ),
                proposer=self.name,
                rationale=(
                    "drinking signal in the last 24h "
                    f"(\"{signal_excerpt}\"); next morning is the right time "
                    "to surface hydration."
                ),
                signal={
                    "phrase_excerpt": signal_excerpt,
                    "phrase_at": match["at"],
                    "matched": match["matched"],
                },
                priority="medium",
            )
        ]

    # -- helpers ------------------------------------------------------------

    async def _fetch_recent_chat(self, user_id: str, hours: int) -> list[Any]:
        if self._chat_fetcher is not None:
            try:
                result = self._chat_fetcher(user_id, hours)
                if inspect.isawaitable(result):
                    result = await result
                return list(result) if result else []
            except Exception:
                logger.exception(
                    "chat_phrase: injected fetcher raised user=%s",
                    user_id[:8] if user_id else "?",
                )
                return []
        return await _default_recent_chat(user_id, hours)

    def _user_already_has_hydration_attention(self, user_id: str) -> bool:
        store = self._store
        if store is None:
            from donna.attention.store import AttentionStore as _Store

            store = _Store()
        try:
            rows = store.list(user_id=user_id)
        except Exception:
            logger.exception(
                "chat_phrase: store.list failed user=%s",
                user_id[:8] if user_id else "?",
            )
            return False
        live_states = {
            AttentionStatus.SHADOW,
            AttentionStatus.OFFERED,
            AttentionStatus.LIVE,
            AttentionStatus.SPEC_DRAFTED,
            AttentionStatus.DRY_RUN_PENDING,
            AttentionStatus.PAUSED,
        }
        for attention in rows:
            if attention.status not in live_states:
                continue
            spec = getattr(attention, "spec", None)
            blob = " ".join(
                str(getattr(spec, k, "") or "")
                for k in ("title", "description")
            ).lower()
            subj = getattr(getattr(spec, "subject", None), "name", "") or ""
            blob = f"{blob} {subj}".lower()
            if any(token in blob for token in _HYDRATION_TOKENS):
                return True
        return False


def _first_drinking_hit(messages: list[Any]) -> dict[str, Any] | None:
    """Return the first chat row that fires the drinking regex, or None.

    ``messages`` is expected to be ordered oldest-first. We scan in that
    direction so the rationale references the originating message rather
    than the latest one.
    """
    for row in messages:
        if getattr(row, "role", "") != "user":
            continue
        text = (getattr(row, "content", "") or "").strip()
        if not text:
            continue
        match = _DRINKING_PATTERN.search(text)
        if match is None:
            continue
        when = getattr(row, "created_at", None)
        return {
            "matched": match.group(0).lower(),
            "text": text,
            "at": when.isoformat() if hasattr(when, "isoformat") else str(when or ""),
        }
    return None


async def _default_recent_chat(user_id: str, hours: int) -> list[Any]:
    """Pull recent ChatMessage rows for the user. Best-effort.

    Async because asyncpg connections are bound to the event loop they
    were created in — bridging across loops via threads triggers
    "Future attached to a different loop" errors. Stay in one loop.

    Returns ``[]`` when the DB is unreachable or the import path isn't
    available (e.g. lightweight CLI runs).
    """
    try:
        # Local imports keep the proposer importable without the full
        # backend present (CLI / unit tests).
        from sqlalchemy import select

        from db.models import ChatMessage
        from db.session import async_session
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=hours
    )

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.created_at >= cutoff)
                    .order_by(ChatMessage.created_at.asc())
                )
            ).scalars().all()
        return list(rows)
    except Exception:
        logger.exception(
            "chat_phrase: chat fetch failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return []


class EntityMentionProposer:
    """TODO: named entities the user references but has no attention for yet."""

    name = "entity_mention"

    def propose(self, user_id: str) -> list[CandidateIntent]:
        return []


# Observation-frequency proposer ────────────────────────────────────────────
#
# When a user logs the same observation type ≥ ``_OBS_FREQ_MIN`` times in
# the last ``_OBS_FREQ_LOOKBACK_DAYS`` days with a median gap ≤
# ``_OBS_FREQ_MAX_MEDIAN_GAP_DAYS``, propose a TALLY tracker for it.
# Catches the canonical "user logged 3 coffees in a week without ever
# asking — propose tracking coffee" pattern.

_OBS_FREQ_LOOKBACK_DAYS = 7
_OBS_FREQ_MIN = 3
_OBS_FREQ_MAX_MEDIAN_GAP_DAYS = 3.0
# Observation types we already get from system signals (calendar sync,
# document ingest, etc.). Skip them — proposing to "track" them would
# be redundant.
_OBS_FREQ_SYSTEM_TYPES: frozenset[str] = frozenset(
    {"document", "calendar", "calendar_entry", "system", "auto"}
)


class ObservationFrequencyProposer:
    """Propose a TALLY when the user repeatedly logs the same obs type
    without an existing tracker for it.

    Single emission per call: pick the most-frequent qualifying type
    and propose. The downstream title-dedup keeps re-shadows quiet.
    """

    name = "observation_frequency"

    def __init__(
        self,
        observation_fetcher: "Callable[[str, int], list[Any]] | None" = None,
        store: "AttentionStore | None" = None,
    ) -> None:
        self._fetcher = observation_fetcher
        self._store = store

    async def propose(self, user_id: str) -> list[CandidateIntent]:
        observations = await self._fetch_observations(
            user_id, _OBS_FREQ_LOOKBACK_DAYS
        )
        if not observations:
            return []

        # Group by type with their event_time so we can compute gap.
        by_type: dict[str, list[datetime]] = {}
        for o in observations:
            obs_type = (getattr(o, "type", "") or "").strip().lower()
            if not obs_type or obs_type in _OBS_FREQ_SYSTEM_TYPES:
                continue
            event_time = getattr(o, "event_time", None)
            if event_time is None:
                continue
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            by_type.setdefault(obs_type, []).append(event_time)

        candidates: list[tuple[str, int, float]] = []
        for obs_type, times in by_type.items():
            if len(times) < _OBS_FREQ_MIN:
                continue
            ordered = sorted(times)
            gaps_days = [
                (ordered[i] - ordered[i - 1]).total_seconds() / 86400
                for i in range(1, len(ordered))
            ]
            if not gaps_days:
                continue
            ordered_gaps = sorted(gaps_days)
            mid = len(ordered_gaps) // 2
            median_gap = (
                ordered_gaps[mid]
                if len(ordered_gaps) % 2
                else 0.5 * (ordered_gaps[mid - 1] + ordered_gaps[mid])
            )
            if median_gap > _OBS_FREQ_MAX_MEDIAN_GAP_DAYS:
                continue
            candidates.append((obs_type, len(times), median_gap))

        if not candidates:
            return []

        # Most frequent first; ties broken by tighter median gap.
        candidates.sort(key=lambda x: (-x[1], x[2]))
        top_type, count, median_gap = candidates[0]

        if self._user_already_has_tracker_for(user_id, top_type):
            return []

        return [
            CandidateIntent(
                raw_intent=(
                    f"set up a TALLY tracker for '{top_type}' — count "
                    f"daily occurrences. user has been logging "
                    f"this casually; a real tracker would surface trends "
                    "and progress on the dashboard."
                ),
                proposer=self.name,
                rationale=(
                    f"logged {count} {top_type} observations in the last "
                    f"{_OBS_FREQ_LOOKBACK_DAYS} days, median gap "
                    f"{median_gap:.1f}d — feels like a real habit."
                ),
                signal={
                    "obs_type": top_type,
                    "count_in_window": count,
                    "median_gap_days": round(median_gap, 2),
                    "lookback_days": _OBS_FREQ_LOOKBACK_DAYS,
                },
                priority="medium",
            )
        ]

    # -- helpers ------------------------------------------------------------

    async def _fetch_observations(self, user_id: str, days: int) -> list[Any]:
        if self._fetcher is not None:
            try:
                result = self._fetcher(user_id, days)
                if inspect.isawaitable(result):
                    result = await result
                return list(result) if result else []
            except Exception:
                logger.exception(
                    "obs_freq: injected fetcher raised user=%s",
                    user_id[:8] if user_id else "?",
                )
                return []
        return await _default_recent_observations(user_id, days)

    def _user_already_has_tracker_for(self, user_id: str, obs_type: str) -> bool:
        """True if the user has any in-flight tracker (TALLY or
        EVENT_STREAM) whose subject normalises onto ``obs_type``."""
        from donna.attention.noise import normalize_tracker_label
        from donna.attention.vocabulary import CardType

        store = self._store
        if store is None:
            from donna.attention.store import AttentionStore as _Store

            store = _Store()
        try:
            rows = store.list(user_id=user_id)
        except Exception:
            logger.exception(
                "obs_freq: store.list failed user=%s",
                user_id[:8] if user_id else "?",
            )
            return False
        target = normalize_tracker_label(obs_type)
        live_states = {
            AttentionStatus.SHADOW,
            AttentionStatus.OFFERED,
            AttentionStatus.LIVE,
            AttentionStatus.SPEC_DRAFTED,
        }
        for a in rows:
            if a.status not in live_states:
                continue
            if a.spec.card not in (CardType.TALLY, CardType.EVENT_STREAM):
                continue
            subj = (
                getattr(getattr(a.spec, "subject", None), "name", "") or ""
            )
            if normalize_tracker_label(subj) == target:
                return True
        return False


async def _default_recent_observations(user_id: str, days: int) -> list[Any]:
    """Pull recent Observation rows for the user. Best-effort."""
    try:
        from sqlalchemy import select

        from db.models import Observation
        from db.session import async_session
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=days
    )

    try:
        async with async_session() as session:
            rows = (
                (
                    await session.execute(
                        select(Observation)
                        .where(Observation.user_id == user_id)
                        .where(Observation.event_time >= cutoff)
                        .order_by(Observation.event_time.asc())
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)
    except Exception:
        logger.exception(
            "obs_freq: observation fetch failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return []


# Deadline proposer ─────────────────────────────────────────────────────────
#
# An OpenLoop with a ``due_at`` set, due in the next
# ``_DEADLINE_LOOKAHEAD_HOURS`` hours, that the user hasn't acknowledged
# recently → propose a PING. The bar is brutal: only fires for real
# deadlines (``due_at`` populated), never for "haven't heard from you."

_DEADLINE_LOOKAHEAD_HOURS = 24
_DEADLINE_MIN_HOURS = 1


class DeadlineProposer:
    """Propose a PING for an open loop approaching its deadline."""

    name = "deadline"

    def __init__(
        self,
        loop_fetcher: "Callable[[str], list[Any]] | None" = None,
        store: "AttentionStore | None" = None,
    ) -> None:
        self._fetcher = loop_fetcher
        self._store = store

    async def propose(self, user_id: str) -> list[CandidateIntent]:
        loops = await self._fetch_open_loops(user_id)
        if not loops:
            return []

        now = datetime.now(timezone.utc)
        candidates: list[tuple[Any, datetime]] = []
        for loop in loops:
            due = getattr(loop, "due_at", None)
            if due is None:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            delta_h = (due - now).total_seconds() / 3600
            if delta_h < _DEADLINE_MIN_HOURS or delta_h > _DEADLINE_LOOKAHEAD_HOURS:
                continue
            candidates.append((loop, due))

        if not candidates:
            return []

        # Earliest due first.
        candidates.sort(key=lambda c: c[1])
        loop, due = candidates[0]

        if self._already_pinged_for_loop(user_id, loop):
            return []

        loop_summary = (getattr(loop, "content", "") or "").strip()[:160]
        local_due = due.isoformat()
        return [
            CandidateIntent(
                raw_intent=(
                    f"set up a PING reminder for the loop \"{loop_summary}\" "
                    f"firing at or just before {local_due} — the user committed "
                    "to this and the deadline is approaching without "
                    "acknowledgement."
                ),
                proposer=self.name,
                rationale=(
                    f"open loop has due_at={local_due}, ~"
                    f"{(due - now).total_seconds() / 3600:.1f}h away."
                ),
                signal={
                    "open_loop_id": getattr(loop, "id", None),
                    "due_at": local_due,
                    "hours_until": round((due - now).total_seconds() / 3600, 2),
                },
                priority="high",
            )
        ]

    # -- helpers ------------------------------------------------------------

    async def _fetch_open_loops(self, user_id: str) -> list[Any]:
        if self._fetcher is not None:
            try:
                result = self._fetcher(user_id)
                if inspect.isawaitable(result):
                    result = await result
                return list(result) if result else []
            except Exception:
                logger.exception(
                    "deadline: injected fetcher raised user=%s",
                    user_id[:8] if user_id else "?",
                )
                return []
        return await _default_open_loops_with_due_at(user_id)

    def _already_pinged_for_loop(self, user_id: str, loop: Any) -> bool:
        """True if a LIVE/SHADOW/OFFERED PING attention already references
        this open_loop (in the spec description or signal payload).

        Conservative — checks for the loop content as a substring of
        the spec description. Misses cases where the description was
        rewritten by the LLM, but those are rare enough that letting a
        second ping through isn't catastrophic.
        """
        store = self._store
        if store is None:
            from donna.attention.store import AttentionStore as _Store

            store = _Store()
        try:
            rows = store.list(user_id=user_id)
        except Exception:
            return False
        from donna.attention.vocabulary import CardType

        live_states = {
            AttentionStatus.SHADOW,
            AttentionStatus.OFFERED,
            AttentionStatus.LIVE,
        }
        loop_id = str(getattr(loop, "id", "") or "")
        loop_content = (getattr(loop, "content", "") or "").strip().lower()
        for a in rows:
            if a.status not in live_states:
                continue
            if a.spec.card is not CardType.PING:
                continue
            desc = (getattr(a.spec, "description", "") or "").lower()
            if loop_id and loop_id in desc:
                return True
            if loop_content and loop_content[:60] in desc:
                return True
        return False


async def _default_open_loops_with_due_at(user_id: str) -> list[Any]:
    """Pull active open_loops with a due_at set, sorted by due date."""
    try:
        from backend.memory.tools._open_loop_view import read_open_loops_unified
        from db.session import async_session
    except Exception:
        return []

    try:
        async with async_session() as session:
            rows = await read_open_loops_unified(
                session,
                user_id=user_id,
                statuses=("active",),
            )
        with_due = [r for r in rows if r.due_at is not None]
        with_due.sort(key=lambda r: r.due_at)
        return with_due
    except Exception:
        logger.exception(
            "deadline: open_loops fetch failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return []


# -- Aggregator --------------------------------------------------------------


_DEFAULT_PROPOSERS: tuple[Proposer, ...] = (
    CalendarRecurrenceProposer(),
    ChatPhraseProposer(),
    ObservationFrequencyProposer(),
    DeadlineProposer(),
    EntityMentionProposer(),
)


async def propose_candidates(
    user_id: str,
    *,
    proposers: tuple[Proposer, ...] | None = None,
) -> list[CandidateIntent]:
    """Run all proposers and return combined candidates (dedup by raw_intent).

    Proposers may be sync (returns ``list[CandidateIntent]``) or async
    (returns awaitable). Async is required for any proposer that touches
    the DB — asyncpg connections are loop-bound, so we keep one loop
    end-to-end.
    """
    proposers = proposers or _DEFAULT_PROPOSERS
    seen: set[str] = set()
    out: list[CandidateIntent] = []
    for p in proposers:
        try:
            result = p.propose(user_id)
            if inspect.isawaitable(result):
                result = await result
            for c in result:
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

    candidates = await propose_candidates(user_id, proposers=proposers)
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
