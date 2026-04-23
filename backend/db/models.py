"""Compatibility exports for the canonical root DB models.

The live runtime owns the production schema in `db.models`. The memory package
keeps importing `backend.db.models`, so this module re-exports the canonical
models instead of maintaining a divergent metadata tree.
"""
from __future__ import annotations

from db.models import *  # noqa: F401,F403
