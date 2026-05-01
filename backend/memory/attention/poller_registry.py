"""Concrete-poller registration.

Importing this module registers every shipped poller into the global
``backend.memory.attention.pollers._REGISTRY`` via each module's import-
time ``register(...)`` call. Engine imports this once at startup; tests
can import it explicitly to ensure a clean registry.

Add new pollers here as a single ``import`` line — keep the engine
ignorant of which concrete pollers exist.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _safe_import(modpath: str) -> None:
    try:
        __import__(modpath)
    except Exception:
        # A misbehaving poller must not block the runtime. Log and move on.
        logger.exception("poller_registry: import failed %s", modpath)


_safe_import("backend.integrations.gmail_attention_poller")
