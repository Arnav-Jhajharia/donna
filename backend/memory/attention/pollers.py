"""External poller protocol + registry for ``card=event_stream`` attentions.

An external poller fetches signal from outside Donna (gmail inbox,
stock prices, Product Hunt, GitHub PRs, calendar events) and writes
``Observation`` rows that the attention engine then rolls up.

Design contract:
    Poller.fetch(attention, ctx) → list[ObservationDraft]

The runtime component is intentionally thin — concrete pollers live
in ``backend/integrations/`` (where the OAuth + connector code already
lives) and just need to:

  1. Implement the ``Poller`` protocol below.
  2. Register themselves under their source-type key.

Today the registry is empty. Each integration adds itself when wired:
    - gmail_inbox → reads new mail since ``last_seen_message_id``
    - stock_quote → fetches a price tick
    - product_hunt → polls launch stats
    - github_prs → lists open PRs

Pattern only — none of these pollers exist yet. The runtime is ready
to consume them when they land.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservationDraft:
    """A poller's output — an observation about to be written.

    The poller produces these; the runtime persists them via
    ``log_observation`` so the schema enforcer + attention engine fire
    automatically. Pollers don't write directly to the DB.
    """

    type: str
    fields: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    tags: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


class Poller(Protocol):
    """One-shot fetch from an external source for an attention."""

    async def fetch(
        self, *, attention: Any, ctx: Any
    ) -> list[ObservationDraft]: ...


_REGISTRY: dict[str, Poller] = {}


def register(source_type: str, poller: Poller) -> None:
    """Register a poller under a ``source_type`` key.

    Source types come from ``AttentionSpec.sources[].type``. Concrete
    integrations call this at import time.
    """
    if source_type in _REGISTRY:
        logger.warning("poller already registered for source_type=%s", source_type)
    _REGISTRY[source_type] = poller


def get_poller(source_type: str) -> Poller | None:
    return _REGISTRY.get(source_type)


def list_registered() -> list[str]:
    return list(_REGISTRY.keys())
