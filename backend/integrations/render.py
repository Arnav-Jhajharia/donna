"""Renders the [INTEGRATIONS] block prepended to user messages.

Block format (toolkit-slug-keyed, status + situation suffix on one line):

    [INTEGRATIONS]
      gmail:          connected · synced 4m ago
      googlecalendar: connected · synced 12m ago · stale
      slack:          pending · link 2m old, still good
      notion:         pending · link 8m old, expired — re-issue if asked
      linear:         pending · waiting on tap
      github:         error · token revoked
      asana:          not connected

The toolkit slug matches what `connect_integration(toolkits=[...])` accepts —
one vocabulary across context block, prompt, and tool args.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence


# Cached redirect URLs are considered "fresh" for this long; mirrors
# REDIRECT_URL_FRESHNESS_SECONDS in backend.integrations.state. We keep
# our own copy here so the renderer doesn't pull in state's import graph.
_REDIRECT_FRESH_SECONDS = 4 * 60

# How old a connected toolkit's last_synced_at can be before we flag the
# row as `stale`. Per-product thresholds reflect ingest cadence:
# gmail's webhook fires per-message so any gap >15min is suspicious;
# calendar syncs every ~30min so we allow longer.
_STALE_THRESHOLD_DEFAULT_S = 30 * 60
_STALE_THRESHOLD_BY_TOOLKIT_S: dict[str, int] = {
    "gmail": 15 * 60,
    "googlecalendar": 60 * 60,
    "googledrive": 60 * 60,
}

# How long a `last_error` snippet can be before we truncate. The model
# only needs the first clue, not a stack trace.
_ERROR_SNIPPET_MAX = 60


# (provider, product) tuples that originate from the `connect_integration`
# google branch get rendered as their composio toolkit slug instead of the
# legacy `google_<product>` label. Anything we don't recognize falls back
# to the safe `provider_product` form so unknown rows still render.
_GOOGLE_PRODUCT_TO_TOOLKIT: dict[str, str] = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
    "drive": "googledrive",
}


def _toolkit_slug(provider: str, product: str) -> str:
    if provider == "google":
        return _GOOGLE_PRODUCT_TO_TOOLKIT.get(product, f"{provider}_{product}")
    if provider == "composio":
        return product
    return f"{provider}_{product}"


def _format_duration(delta_seconds: float) -> str:
    """Compact duration label; caller appends the right tail (' ago', ' old')."""
    if delta_seconds < 60:
        return f"{int(delta_seconds)}s"
    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h"
    days = int(hours // 24)
    return f"{days}d"


def _connected_suffix(row, now: datetime, toolkit: str) -> str:
    last_sync = getattr(row, "last_synced_at", None)
    if last_sync is None:
        return "connected · just connected"
    delta = (now - last_sync).total_seconds()
    age = _format_duration(delta)
    threshold = _STALE_THRESHOLD_BY_TOOLKIT_S.get(
        toolkit, _STALE_THRESHOLD_DEFAULT_S
    )
    if delta > threshold:
        return f"connected · synced {age} ago · stale"
    return f"connected · synced {age} ago"


def _pending_suffix(row, now: datetime) -> str:
    issued_at = getattr(row, "redirect_url_issued_at", None)
    url = getattr(row, "redirect_url", None)
    if not url or issued_at is None:
        return "pending · waiting on tap"
    delta = (now - issued_at).total_seconds()
    age = _format_duration(delta)
    if delta <= _REDIRECT_FRESH_SECONDS:
        return f"pending · link {age} old, still good"
    return f"pending · link {age} old, expired — re-issue if asked"


def _error_suffix(row) -> str:
    msg = (getattr(row, "last_error", None) or "").strip()
    if not msg:
        return "error"
    snippet = msg if len(msg) <= _ERROR_SNIPPET_MAX else msg[: _ERROR_SNIPPET_MAX - 1] + "…"
    return f"error · {snippet}"


def _line(row, *, label_width: int, now: datetime) -> str:
    toolkit = _toolkit_slug(row.provider, row.product)
    label = f"{toolkit}:".ljust(label_width)
    status = row.status
    if status == "connected":
        suffix = _connected_suffix(row, now, toolkit)
    elif status == "pending":
        suffix = _pending_suffix(row, now)
    elif status == "error":
        suffix = _error_suffix(row)
    elif status == "revoked":
        suffix = "revoked · ask before reconnecting"
    elif status == "not_connected":
        suffix = "not connected"
    else:
        suffix = status
    return f"  {label} {suffix}".rstrip()


def render_integrations_block(
    rows: Sequence,
    *,
    now: datetime | None = None,
) -> str:
    if not rows:
        return ""
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    label_width = (
        max(len(_toolkit_slug(r.provider, r.product)) for r in rows) + 1
    )
    lines = ["[INTEGRATIONS]"]
    for row in rows:
        lines.append(_line(row, label_width=label_width, now=now))
    return "\n".join(lines)


def render_oauth_in_flight_block(
    rows: Sequence,
    *,
    now: datetime | None = None,
) -> str:
    """Render an [OAUTH IN FLIGHT] block when any pending row has a fresh
    cached redirect URL — i.e., the user just got a consent link and the
    next turn might be them coming back to confirm.

    Toolkits issued in the same chain share a `redirect_url`; we group by
    that URL so a multi-toolkit chain renders as one line.
    """
    if not rows:
        return ""
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = timedelta(seconds=_REDIRECT_FRESH_SECONDS)
    chains: dict[str, list] = {}
    for row in rows:
        if getattr(row, "status", None) != "pending":
            continue
        url = getattr(row, "redirect_url", None)
        issued_at = getattr(row, "redirect_url_issued_at", None)
        if not url or issued_at is None:
            continue
        if (now - issued_at) > cutoff:
            continue
        chains.setdefault(url, []).append(row)
    if not chains:
        return ""
    lines = ["[OAUTH IN FLIGHT]"]
    for url, group in chains.items():
        slugs = sorted({_toolkit_slug(r.provider, r.product) for r in group})
        # All rows in a chain share an issued_at; the chain head is whichever
        # row was written first within this group, so pick the min.
        issued_at = min(r.redirect_url_issued_at for r in group)
        age = _format_duration((now - issued_at).total_seconds())
        lines.append(f"  {', '.join(slugs)} — link sent {age} ago")
    return "\n".join(lines)
