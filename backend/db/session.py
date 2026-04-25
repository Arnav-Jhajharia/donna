"""Compatibility exports for the canonical root DB session.

`backend.memory` was ported with `backend.db.*` imports, while the live app
uses root `db.*`. Keep the memory boundary stable by forwarding to root DB.
"""
from __future__ import annotations

from db.session import _engine, async_session


def get_engine():
    return _engine
