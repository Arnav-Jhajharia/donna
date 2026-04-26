"""Autonomous attention spawners (Layer B).

Three signal sources feed the existing attention pipeline:

- ``calendar`` — calendar event upserts + a daily 24h-ahead sweep
- ``observation`` — observations logged via ``log_observation``
- in-turn intent capture — handled in ``donna_runtime/prompt.py``,
  no module needed here

Each spawner classifies its signal against ``templates.json`` and feeds
natural-language intents into ``donna_runtime.tools._create_and_queue_attention``
with ``origin="donna"``. HIGH-confidence templates land LIVE; MEDIUM
templates persist as SHADOW for the existing promote cycle to handle;
LOW templates are dropped.

All entry points are best-effort and never raise to their callers — a
broken spawner must not break the underlying signal write.
"""
from __future__ import annotations

from proactive.spawners.shape import InferredIntent, SpawnConfidence

__all__ = ["InferredIntent", "SpawnConfidence"]
