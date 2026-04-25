from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.integrations.render import render_integrations_block


def _row(provider, product, status, last_synced_at=None) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        product=product,
        status=status,
        last_synced_at=last_synced_at,
        last_error=None,
    )


def test_render_empty_returns_empty_string() -> None:
    assert render_integrations_block([]) == ""


def test_render_connected_with_sync_age() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row("google", "calendar", "connected", now - timedelta(minutes=8)),
        _row("google", "gmail", "not_connected"),
    ]
    out = render_integrations_block(rows, now=now)
    assert "[INTEGRATIONS]" in out
    assert "google_calendar: connected" in out
    assert "synced 8m ago" in out
    assert "google_gmail:    not connected" in out


def test_render_pending_state() -> None:
    out = render_integrations_block([_row("google", "calendar", "pending")])
    assert "google_calendar: pending" in out
    assert "synced" not in out


def test_render_error_state() -> None:
    row = _row("google", "calendar", "error")
    row.last_error = "401 unauthorized"
    out = render_integrations_block([row])
    assert "google_calendar: error" in out
    assert "401 unauthorized" in out
