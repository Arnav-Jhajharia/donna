"""Source / Deriver / Surfacer protocols + the orchestrator.

The runtime is intentionally simple: a tiny dispatcher that takes an
attention, picks a (Source, Deriver, Surfacer) tuple based on its
``card`` type, runs them in order, and writes ``current_state`` back.

Each protocol is async and best-effort. Failures degrade through ``None``
and a logged exception — never crash the worker that called us.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceResult:
    """What a Source returns to the deriver.

    Generic shape so the Deriver layer can compose. ``items`` is the
    list of raw data points; ``meta`` carries lane-specific extras
    (e.g. day window, freshness markers, source counts).
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeriveContext:
    """Inputs handed to a Deriver alongside the SourceResult.

    Carries the spec snippet relevant to derive (target, schema_hint,
    extractor.prompt) plus user-local clock so derivers can window
    correctly without re-querying.
    """

    user_id: str
    user_local_now: datetime
    user_local_day: str  # ISO date in user-local
    spec_extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SurfaceResult:
    """Surfacer return value — what the side-effect was.

    ``kind`` is one of {"silent", "burst", "escalation", "nudge", "skip"}.
    ``message`` is the WhatsApp text when one was sent; None for silent.
    """

    kind: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Source(Protocol):
    """Reads input data for an attention."""

    async def read(
        self, *, attention: Any, ctx: DeriveContext
    ) -> SourceResult: ...


class Deriver(Protocol):
    """Turns SourceResult into a current_state dict."""

    async def derive(
        self, *, attention: Any, source: SourceResult, ctx: DeriveContext
    ) -> dict[str, Any]: ...


class Surfacer(Protocol):
    """Decides whether/how to push, given current_state + spec.

    May be a no-op (default=silent) or fire a WhatsApp burst. Always
    updates timestamps via the caller; the Surfacer just returns
    intent.
    """

    async def surface(
        self,
        *,
        attention: Any,
        current_state: dict[str, Any],
        ctx: DeriveContext,
        trigger: str,
    ) -> SurfaceResult: ...


async def run_attention_cycle(
    *,
    attention: Any,
    source: Source,
    deriver: Deriver,
    surfacer: Surfacer,
    ctx: DeriveContext,
    trigger: str,
) -> tuple[dict[str, Any], SurfaceResult]:
    """Run one cycle: Source → Deriver → Surfacer.

    Returns ``(current_state, surface_result)``. Caller is responsible
    for persisting ``current_state`` and applying surface side-effects.
    """
    src = await source.read(attention=attention, ctx=ctx)
    state = await deriver.derive(attention=attention, source=src, ctx=ctx)
    state.setdefault("computed_at", ctx.user_local_now.isoformat())
    state.setdefault("day", ctx.user_local_day)
    surface = await surfacer.surface(
        attention=attention,
        current_state=state,
        ctx=ctx,
        trigger=trigger,
    )
    return state, surface
