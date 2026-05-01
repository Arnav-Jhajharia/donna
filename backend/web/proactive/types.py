"""DTOs for the proactive search subsystem — all immutable.

Mirrors the shape used elsewhere in the codebase: frozen dataclasses,
``Literal`` for closed sets, no behaviour on the types themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ExaTool = Literal["search", "find_similar", "research", "webset", "monitor"]
RenderHint = Literal["short_text", "long_text", "card", "image"]
TriggerKind = Literal["morning", "drain", "pre_event", "manual"]

VALID_TOOLS: frozenset[str] = frozenset(
    {"search", "find_similar", "research", "webset", "monitor"}
)
VALID_RENDER_HINTS: frozenset[str] = frozenset(
    {"short_text", "long_text", "card", "image"}
)
VALID_TRIGGERS: frozenset[str] = frozenset(
    {"morning", "drain", "pre_event", "manual"}
)


@dataclass(frozen=True)
class SignalSummary:
    """One pending Exa monitor hit, summarized for the reasoner."""

    signal_id: str
    intent_key: str
    title: str
    url: str
    snippet: str
    published: str | None = None


@dataclass(frozen=True)
class ProactiveContext:
    """Snapshot of what the brain knows about the user RIGHT NOW.

    ``trigger`` is which scheduler fired this tick — the reasoner uses
    this to branch its prompt. ``signal_queue`` carries pending Exa
    monitor hits awaiting judgment; for ``trigger="drain"`` ticks this
    list is the primary input.
    """

    user_id: str
    profile_blurb: str = ""
    situation_brief: str = ""
    recent_thread: str = ""
    current_datetime: str = ""
    last_proactive_at: str | None = None
    trigger: TriggerKind = "manual"
    signal_queue: tuple[SignalSummary, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProactiveMove:
    """One concrete proactive search action.

    The reasoner emits these. Each move carries a hypothesis-shaped
    rationale: what it's *betting* the world contains, anchored on a
    concrete signal from the user's state, with a stated payoff.
    """

    rationale: str  # legacy free-form, kept for backward compat
    tool: ExaTool
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.5
    render_hint: RenderHint = "short_text"
    dedup_key: str = ""
    # New hypothesis fields — may be empty for legacy callers
    hypothesis: str = ""
    user_signal: str = ""
    payoff_if_hit: str = ""


@dataclass(frozen=True)
class ProactiveResult:
    """Result of executing one move. Carries the move forward + the payload."""

    move: ProactiveMove
    status: Literal["ok", "no_hits", "degraded", "skipped"]
    payload: Any = None
    elapsed_ms: int = 0
    skipped_reason: str | None = None
