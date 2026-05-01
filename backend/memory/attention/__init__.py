"""Attention runtime — turns the spec into behavior.

The attention spec (donna/attention/schema.py) is rich and declarative.
This module is the runtime engine that consumes it. Three pluggable
concerns:

    Source   — what input the attention listens to (observations, time,
               external pollers, calendar events, open loops)
    Deriver  — how sources turn into ``current_state`` (sum, count, latest,
               age, checklist, narrative summary)
    Surfacer — when state changes or time fires, what does the attention DO
               (silent, escalation, scheduled burst, nudge-on-stale)

Each card type is a configuration of (Source, Deriver, Surfacer).

This module is event-driven, not poll-based:
- Observation writes flip a dirty bit and recompute inline.
- Schedule fires (existing schedule_worker) trigger derive + surface.
- A backstop hourly sweep handles missed events + day rollovers.

``current_state`` lives in ``AttentionRow.payload['current_state']`` so
no schema migration is needed today. ``AttentionTickRow`` continues to
serve as the append-only audit trail of evaluations.
"""
from backend.memory.attention.runtime import (
    DeriveContext,
    Deriver,
    Source,
    SourceResult,
    Surfacer,
    SurfaceResult,
    run_attention_cycle,
)

__all__ = [
    "DeriveContext",
    "Deriver",
    "Source",
    "SourceResult",
    "Surfacer",
    "SurfaceResult",
    "run_attention_cycle",
]
