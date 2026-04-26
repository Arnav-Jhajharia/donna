"""DTOs for the proactive search subsystem — all immutable.

Mirrors the shape used elsewhere in the codebase: frozen dataclasses,
``Literal`` for closed sets, no behaviour on the types themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ExaTool = Literal["search", "find_similar", "research", "webset", "monitor"]
RenderHint = Literal["short_text", "long_text", "card", "image"]

VALID_TOOLS: frozenset[str] = frozenset(
    {"search", "find_similar", "research", "webset", "monitor"}
)
VALID_RENDER_HINTS: frozenset[str] = frozenset(
    {"short_text", "long_text", "card", "image"}
)


@dataclass(frozen=True)
class ProactiveContext:
    """Snapshot of what the brain knows about the user RIGHT NOW.

    Inputs to ``query_creation.create_proactive_moves``. Treat as
    immutable; the reasoner only reads.
    """

    user_id: str
    profile_blurb: str = ""
    situation_brief: str = ""
    recent_thread: str = ""
    current_datetime: str = ""
    last_proactive_at: str | None = None


@dataclass(frozen=True)
class ProactiveMove:
    """One concrete proactive search action.

    The reasoner emits these. The executor dispatches them. A downstream
    judge decides whether the result is worth interrupting the user with.
    """

    rationale: str
    tool: ExaTool
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.5
    render_hint: RenderHint = "short_text"
    dedup_key: str = ""


@dataclass(frozen=True)
class ProactiveResult:
    """Result of executing one move. Carries the move forward + the payload."""

    move: ProactiveMove
    status: Literal["ok", "no_hits", "degraded", "skipped"]
    payload: Any = None
    elapsed_ms: int = 0
    skipped_reason: str | None = None
