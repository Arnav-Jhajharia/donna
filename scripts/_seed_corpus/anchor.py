"""Anchor-date resolution for the seed corpus.

The corpus is deterministic in both data *and* time placement: every row
gets dated relative to a fixed anchor. Operators can pin the anchor via
``--anchor-date`` for regression reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class AnchorWindow:
    """Anchor plus the derived 30-day-back / 30-day-forward bounds."""

    anchor: datetime  # naive UTC
    start: datetime
    end: datetime


def resolve_anchor(value: str | None = None) -> AnchorWindow:
    """Return a 61-day window (anchor - 30d .. anchor + 30d).

    ``value`` is an ISO-8601 string; when absent we use current UTC.
    Returned datetimes are naive UTC to match the DB column convention.
    """
    if value and value.strip():
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        anchor = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    else:
        anchor = datetime.now(timezone.utc).replace(tzinfo=None)
    return AnchorWindow(
        anchor=anchor,
        start=anchor - timedelta(days=30),
        end=anchor + timedelta(days=30),
    )
