"""Bi-temporal facts repository.

Two time axes:
  t_valid_*    — when the fact was true in the real world
  t_recorded_* — when we learned / stopped believing the fact

See :class:`db.models.Fact` for the full schema.
"""
from __future__ import annotations

from backend.memory.facts.bitemporal import (
    get_as_of,
    get_current,
    list_history,
    record_fact,
    supersede_fact,
    update_fact,
)

__all__ = [
    "record_fact",
    "update_fact",
    "supersede_fact",
    "get_current",
    "get_as_of",
    "list_history",
]
