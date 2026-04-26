"""Shared dataclasses for spawners.

Kept tiny and dependency-free so any spawner module can import from
here without cycles. The materialiser in ``materialise.py`` consumes
``InferredIntent`` and dispatches into the existing attention pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpawnConfidence(str, Enum):
    """Per-template confidence — drives auto_live behaviour.

    HIGH   → LIVE attention immediately (user can cancel)
    MEDIUM → SHADOW attention; existing promote cycle escalates to OFFERED
    LOW    → drop (no attention created)
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def parse(cls, value: str | None) -> "SpawnConfidence":
        if not value:
            return cls.LOW
        try:
            return cls(value.lower())
        except ValueError:
            return cls.LOW


@dataclass(frozen=True)
class InferredIntent:
    """One attention proposal a spawner derived from a single signal.

    ``text`` is the raw natural-language string the author pipeline
    parses. ``confidence`` decides LIVE vs SHADOW vs drop.
    ``dedup_key`` is the spawn-side dedup token; the materialiser
    refuses to spawn twice with the same key.
    """

    text: str
    confidence: SpawnConfidence
    dedup_key: str
    template_id: str
    rationale: str = ""
    signal: dict[str, Any] = field(default_factory=dict)
