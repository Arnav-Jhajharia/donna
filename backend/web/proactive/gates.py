"""Gates — pre-execution filters that drop moves before Exa is called.

Three gates, applied in order:

1. **DedupLedger** — kills moves whose ``dedup_key`` was already fired
   recently (per user, with TTL). Stops Donna from re-pinging the user
   about the same intent every loop.

2. **CostBudget** — caps total moves per turn and per day. The reasoner
   may emit 0..N; the budget keeps a runaway loop from burning Exa
   credits. Counted in "moves" not raw dollars; all lanes count equal.

3. **HeuristicRelevance** — pure-string filter for the obvious bad
   shapes: empty query, sub-3-token vague queries on cheap lanes,
   wellness/mindfulness keyword sniff. The system prompt already forbids
   these but the gate is defense in depth.

All three are pure-data: no DB, no LLM. The ledger is in-memory by
default (fine for a single proactive worker); a Redis backend can drop
in later behind the same protocol.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from backend.web.proactive.types import ProactiveMove


# ---------------------------------------------------------------------------
# heuristic relevance
# ---------------------------------------------------------------------------


_BANNED_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "mindfulness",
        "self-help",
        "self help",
        "wellness tips",
        "you might like",
        "things to try",
        "life hacks",
    }
)

_MIN_TOKENS_FOR_CHEAP_LANE = 3


def is_obviously_bad(move: ProactiveMove) -> str | None:
    """Return a reason string if the move should be dropped, else None."""
    q = (move.query or "").strip()
    if not q:
        return "empty query"
    low = q.lower()
    for needle in _BANNED_SUBSTRINGS:
        if needle in low:
            return f"banned phrase: {needle!r}"
    if move.tool == "search":
        tokens = [t for t in low.split() if t]
        if len(tokens) < _MIN_TOKENS_FOR_CHEAP_LANE and not low.startswith("http"):
            return "query too vague for search lane"
    if move.tool == "find_similar" and not low.startswith(("http://", "https://")):
        return "find_similar requires a URL seed"
    return None


# ---------------------------------------------------------------------------
# dedup ledger
# ---------------------------------------------------------------------------


class DedupStore(Protocol):
    """Minimal async protocol so we can swap Postgres / Redis / fakes."""

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool: ...
    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None: ...


@dataclass
class InMemoryDedupStore:
    """Per-process ledger keyed by ``(user_id, dedup_key)`` — async API.

    Kept as a fallback for tests and CLI dry-runs. Production runs use
    ``backend.web.proactive.store.PostgresDedupStore``.
    """

    ttl_seconds: float = 6 * 3600.0  # 6h
    _entries: dict[tuple[str, str], float] = field(default_factory=dict)

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool:
        key = (user_id, dedup_key)
        ts = self._entries.get(key)
        if ts is None:
            return False
        if (now - ts) >= self.ttl_seconds:
            self._entries.pop(key, None)
            return False
        return True

    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None:
        self._entries[(user_id, dedup_key)] = now


# ---------------------------------------------------------------------------
# cost budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostBudget:
    """Caps on how many moves a user can fire.

    ``per_turn`` bounds a single proactive cycle.
    ``per_day`` is a soft daily cap; enforcement requires a counter that
    persists across turns and is left to the caller (the gate just
    accepts an injected ``daily_used`` count).
    """

    # Conservative defaults for the launch window: at most 1 proactive
    # ping per turn, 3 per day. Tuned high-precision; loosen once
    # calibration is settled.
    per_turn: int = 1
    per_day: int = 3


# ---------------------------------------------------------------------------
# unified gate runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDrop:
    """A move that didn't make it past the gates."""

    move: ProactiveMove
    reason: str


@dataclass(frozen=True)
class GateOutcome:
    """What survived and what got dropped (with reasons)."""

    accepted: list[ProactiveMove]
    dropped: list[GateDrop]


async def apply_gates(
    moves: list[ProactiveMove],
    *,
    user_id: str,
    ledger: DedupStore,
    budget: CostBudget = CostBudget(),
    daily_used: int = 0,
    now: float | None = None,
) -> GateOutcome:
    """Filter moves through dedup → relevance → budget. Async because
    the ledger is async (Postgres-backed in prod, in-memory in tests).

    The ledger is *read* but not mutated — call ``ledger.mark_async`` on
    each accepted move only after the worth-telling judge says yes.
    """
    now_ts = float(now if now is not None else time.time())

    accepted: list[ProactiveMove] = []
    dropped: list[GateDrop] = []
    daily_remaining = max(0, budget.per_day - max(0, int(daily_used)))

    for move in moves:
        if len(accepted) >= budget.per_turn:
            dropped.append(GateDrop(move=move, reason="per-turn budget exhausted"))
            continue
        if daily_remaining <= 0:
            dropped.append(GateDrop(move=move, reason="per-day budget exhausted"))
            continue
        bad = is_obviously_bad(move)
        if bad:
            dropped.append(GateDrop(move=move, reason=bad))
            continue
        if await ledger.seen_async(user_id, move.dedup_key, now=now_ts):
            dropped.append(GateDrop(move=move, reason="dedup: recently fired"))
            continue
        accepted.append(move)
        daily_remaining -= 1

    return GateOutcome(accepted=accepted, dropped=dropped)
