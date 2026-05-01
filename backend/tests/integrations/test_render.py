from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.integrations.render import (
    render_integrations_block,
    render_oauth_in_flight_block,
)


def _row(
    provider,
    product,
    status,
    last_synced_at=None,
    *,
    redirect_url=None,
    redirect_url_issued_at=None,
    last_error=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        product=product,
        status=status,
        last_synced_at=last_synced_at,
        last_error=last_error,
        redirect_url=redirect_url,
        redirect_url_issued_at=redirect_url_issued_at,
    )


# --- render_integrations_block ----------------------------------------------


def test_render_empty_returns_empty_string() -> None:
    assert render_integrations_block([]) == ""


def test_render_uses_toolkit_slug_not_provider_product() -> None:
    """Google rows render as their composio toolkit slug (gmail,
    googlecalendar, googledrive). Composio rows render as the slug verbatim.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row("google", "gmail", "connected", now - timedelta(minutes=5)),
        _row("google", "calendar", "connected", now - timedelta(minutes=10)),
        _row("google", "drive", "connected", now - timedelta(minutes=12)),
        _row("composio", "slack", "not_connected"),
    ]
    out = render_integrations_block(rows, now=now)
    assert "[INTEGRATIONS]" in out
    assert "gmail:" in out
    assert "googlecalendar:" in out
    assert "googledrive:" in out
    assert "slack:" in out
    # Legacy `provider_product` form must NOT appear.
    assert "google_gmail" not in out
    assert "google_calendar" not in out
    assert "composio_slack" not in out


def test_render_connected_with_sync_age() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [_row("google", "gmail", "connected", now - timedelta(minutes=4))]
    out = render_integrations_block(rows, now=now)
    assert "gmail:" in out
    assert "connected · synced 4m ago" in out
    assert "stale" not in out


def test_render_flags_stale_when_sync_exceeds_threshold() -> None:
    """Gmail's stale threshold is 15min; a 30-min-old sync should flag."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [_row("google", "gmail", "connected", now - timedelta(minutes=30))]
    out = render_integrations_block(rows, now=now)
    assert "connected · synced 30m ago · stale" in out


def test_render_calendar_stale_threshold_is_higher_than_gmail() -> None:
    """googlecalendar tolerates longer gaps; 30 min is fine, 90 min is stale."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows_fresh = [
        _row("google", "calendar", "connected", now - timedelta(minutes=30))
    ]
    rows_stale = [
        _row("google", "calendar", "connected", now - timedelta(minutes=90))
    ]
    assert "stale" not in render_integrations_block(rows_fresh, now=now)
    assert "stale" in render_integrations_block(rows_stale, now=now)


def test_render_connected_without_last_synced() -> None:
    out = render_integrations_block(
        [_row("google", "gmail", "connected", None)]
    )
    assert "connected · just connected" in out


def test_render_pending_with_fresh_link() -> None:
    """A pending row whose redirect URL is <4min old should advertise the
    link as live so Donna doesn't burn credits re-issuing it."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row(
            "google",
            "gmail",
            "pending",
            redirect_url="https://composio.dev/x",
            redirect_url_issued_at=now - timedelta(minutes=2),
        )
    ]
    out = render_integrations_block(rows, now=now)
    assert "pending · link 2m old, still good" in out


def test_render_pending_with_expired_link() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row(
            "google",
            "gmail",
            "pending",
            redirect_url="https://composio.dev/x",
            redirect_url_issued_at=now - timedelta(minutes=8),
        )
    ]
    out = render_integrations_block(rows, now=now)
    assert "pending · link 8m old, expired — re-issue if asked" in out


def test_render_pending_without_cached_link() -> None:
    out = render_integrations_block([_row("google", "gmail", "pending")])
    assert "pending · waiting on tap" in out


def test_render_error_state_includes_last_error_snippet() -> None:
    out = render_integrations_block(
        [_row("google", "gmail", "error", last_error="401 unauthorized")]
    )
    assert "error · 401 unauthorized" in out


def test_render_error_state_truncates_long_last_error() -> None:
    long_msg = "boom " * 50  # 250 chars
    out = render_integrations_block(
        [_row("google", "gmail", "error", last_error=long_msg)]
    )
    # Truncation marker present; original verbose message NOT.
    assert "…" in out
    assert long_msg not in out


def test_render_revoked_state() -> None:
    out = render_integrations_block([_row("google", "gmail", "revoked")])
    assert "revoked · ask before reconnecting" in out


def test_render_not_connected() -> None:
    out = render_integrations_block(
        [_row("composio", "notion", "not_connected")]
    )
    assert "notion:" in out
    assert "not connected" in out


def test_render_label_widths_align() -> None:
    """All status columns line up. Label width = longest slug + 1 (for ':')."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row("google", "gmail", "connected", now - timedelta(minutes=1)),
        _row("google", "calendar", "connected", now - timedelta(minutes=1)),
    ]
    out = render_integrations_block(rows, now=now)
    body_lines = [l for l in out.splitlines() if l.startswith("  ")]
    # Position of "connected" should be identical across rows.
    positions = {l.index("connected") for l in body_lines}
    assert len(positions) == 1


# --- render_oauth_in_flight_block --------------------------------------------


def test_oauth_in_flight_empty_when_no_pending() -> None:
    rows = [_row("google", "gmail", "connected")]
    assert render_oauth_in_flight_block(rows) == ""


def test_oauth_in_flight_renders_when_pending_link_fresh() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row(
            "google",
            "gmail",
            "pending",
            redirect_url="https://composio.dev/x",
            redirect_url_issued_at=now - timedelta(seconds=47),
        )
    ]
    out = render_oauth_in_flight_block(rows, now=now)
    assert "[OAUTH IN FLIGHT]" in out
    assert "gmail" in out
    assert "47s ago" in out


def test_oauth_in_flight_groups_chain_by_shared_url() -> None:
    """Toolkits issued in one chain share a redirect_url; render as one line."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    issued = now - timedelta(seconds=30)
    rows = [
        _row(
            "google",
            "gmail",
            "pending",
            redirect_url="https://composio.dev/chain1",
            redirect_url_issued_at=issued,
        ),
        _row(
            "google",
            "calendar",
            "pending",
            redirect_url="https://composio.dev/chain1",
            redirect_url_issued_at=issued,
        ),
    ]
    out = render_oauth_in_flight_block(rows, now=now)
    body_lines = [l for l in out.splitlines() if l.startswith("  ")]
    assert len(body_lines) == 1
    assert "gmail, googlecalendar" in body_lines[0]
    assert "30s ago" in body_lines[0]


def test_oauth_in_flight_skips_expired_links() -> None:
    """A pending row with a stale redirect URL doesn't belong in the
    in-flight block — the link is dead, the user is past the live window."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row(
            "google",
            "gmail",
            "pending",
            redirect_url="https://composio.dev/x",
            redirect_url_issued_at=now - timedelta(minutes=10),
        )
    ]
    assert render_oauth_in_flight_block(rows, now=now) == ""


def test_oauth_in_flight_skips_pending_without_url() -> None:
    rows = [_row("google", "gmail", "pending")]
    assert render_oauth_in_flight_block(rows) == ""
