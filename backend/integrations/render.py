"""Renders the [INTEGRATIONS] block prepended to user messages."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence


_LABEL_WIDTH = len("google_calendar:")


def _format_age(delta_seconds: float) -> str:
    if delta_seconds < 60:
        return "just now"
    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"synced {minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"synced {hours}h ago"
    days = int(hours // 24)
    return f"synced {days}d ago"


def _line(row, now: datetime) -> str:
    label = f"{row.provider}_{row.product}:".ljust(_LABEL_WIDTH)
    status = row.status if row.status != "not_connected" else "not connected"
    suffix = ""
    if row.status == "connected" and row.last_synced_at is not None:
        delta = (now - row.last_synced_at).total_seconds()
        suffix = " · " + _format_age(delta)
    if row.status == "error" and getattr(row, "last_error", None):
        suffix = f" · {row.last_error}"
    return f"  {label} {status}{suffix}".rstrip()


def render_integrations_block(
    rows: Sequence,
    *,
    now: datetime | None = None,
) -> str:
    if not rows:
        return ""
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = ["[INTEGRATIONS]"]
    for row in rows:
        lines.append(_line(row, now))
    return "\n".join(lines)
