"""Tests for backend.integrations.oauth_watcher.

Covers:
- Happy path: all toolkits flip ACTIVE on second poll, DB marked, bootstrap
  fires when google toolkits land.
- Timeout: never goes ACTIVE, bootstrap NOT called, warning logged.
- Partial: 2/3 active by deadline, DB marked for the 2, bootstrap still fires
  because gmail is active.
- Non-google toolkits (slack, notion): DB marked but bootstrap NOT fired —
  the gmail-driven biography algorithm is gmail-specific.
- Hook plumbing: post_tool_hook spawns the watcher only for
  connect_integration.
"""
from __future__ import annotations

import logging

import pytest

from backend.integrations import oauth_watcher, state


class _FakeConnectedAccount:
    def __init__(self, *, id: str, status: str, toolkit_slug: str | None):
        self.id = id
        self.status = status

        class _T:
            slug = toolkit_slug

        self.toolkit = _T() if toolkit_slug is not None else None


class _FakeListing:
    def __init__(self, items):
        self.items = items


class _FakeConnectedAccounts:
    """Returns a different list for each successive .list() call so we can
    simulate the OAuth completion flipping over time."""

    def __init__(self, sequence: list[list[_FakeConnectedAccount]]):
        self._sequence = sequence
        self.calls: int = 0

    def list(self, *, user_ids, toolkit_slugs):
        idx = min(self.calls, len(self._sequence) - 1)
        self.calls += 1
        return _FakeListing(self._sequence[idx])


class _FakeComposio:
    def __init__(self, sequence):
        self.connected_accounts = _FakeConnectedAccounts(sequence)


@pytest.fixture
def fast_intervals(monkeypatch):
    """Speed the watcher up so tests finish in milliseconds, not minutes."""
    monkeypatch.setattr(oauth_watcher, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(oauth_watcher, "DEFAULT_TIMEOUT_SECONDS", 1)


@pytest.fixture
def stub_bootstrap(monkeypatch):
    """Capture run_bootstrap_async calls without doing real work."""
    captured = {"calls": []}

    async def _fake(user_id):
        captured["calls"].append(user_id)

    import api.composio_webhook as wh

    monkeypatch.setattr(wh, "run_bootstrap_async", _fake)
    return captured


@pytest.mark.asyncio
async def test_watcher_marks_db_and_fires_bootstrap_when_all_google_active(
    db, monkeypatch, fast_intervals, stub_bootstrap
):
    sequence = [
        [],
        [
            _FakeConnectedAccount(id="ca_g", status="ACTIVE", toolkit_slug="gmail"),
            _FakeConnectedAccount(
                id="ca_c", status="ACTIVE", toolkit_slug="googlecalendar"
            ),
            _FakeConnectedAccount(
                id="ca_d", status="ACTIVE", toolkit_slug="googledrive"
            ),
        ],
    ]
    fake = _FakeComposio(sequence)
    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", lambda: fake
    )

    await oauth_watcher.watch_oauth_and_bootstrap(
        user_id="u1",
        toolkits=["gmail", "googlecalendar", "googledrive"],
        timeout_seconds=2,
        poll_interval=0,
    )

    assert stub_bootstrap["calls"] == ["u1"]

    gmail = await state.get_integration_status("u1", "google", "gmail")
    cal = await state.get_integration_status("u1", "google", "calendar")
    drive = await state.get_integration_status("u1", "google", "drive")
    assert gmail.status == "connected"
    assert gmail.composio_connection_id == "ca_g"
    assert cal.status == "connected"
    assert cal.composio_connection_id == "ca_c"
    assert drive.status == "connected"
    assert drive.composio_connection_id == "ca_d"


@pytest.mark.asyncio
async def test_watcher_timeout_no_active_no_bootstrap(
    db, monkeypatch, fast_intervals, stub_bootstrap, caplog
):
    sequence = [[], [], []]  # never goes active
    fake = _FakeComposio(sequence)
    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", lambda: fake
    )

    with caplog.at_level(logging.WARNING, logger="backend.integrations.oauth_watcher"):
        await oauth_watcher.watch_oauth_and_bootstrap(
            user_id="u1",
            toolkits=["gmail", "googlecalendar"],
            timeout_seconds=0,
            poll_interval=0,
        )

    assert stub_bootstrap["calls"] == []
    gmail = await state.get_integration_status("u1", "google", "gmail")
    assert gmail is None
    assert any(
        "timeout" in record.message.lower() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_watcher_partial_marks_what_it_can_and_fires_bootstrap(
    db, monkeypatch, fast_intervals, stub_bootstrap
):
    """gmail + calendar active, drive not — bootstrap still fires (gmail is
    in the active set)."""
    items = [
        _FakeConnectedAccount(id="ca_g", status="ACTIVE", toolkit_slug="gmail"),
        _FakeConnectedAccount(
            id="ca_c", status="ACTIVE", toolkit_slug="googlecalendar"
        ),
    ]
    fake = _FakeComposio([items, items, items])
    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", lambda: fake
    )

    await oauth_watcher.watch_oauth_and_bootstrap(
        user_id="u1",
        toolkits=["gmail", "googlecalendar", "googledrive"],
        timeout_seconds=0,
        poll_interval=0,
    )

    assert stub_bootstrap["calls"] == ["u1"]

    gmail = await state.get_integration_status("u1", "google", "gmail")
    cal = await state.get_integration_status("u1", "google", "calendar")
    drive = await state.get_integration_status("u1", "google", "drive")
    assert gmail.status == "connected"
    assert cal.status == "connected"
    assert drive is None


@pytest.mark.asyncio
async def test_watcher_skips_unknown_toolkits_when_none_request(
    db, monkeypatch, fast_intervals, stub_bootstrap
):
    """Empty toolkits list returns immediately, no Composio call."""
    called = {"composio": 0}

    def _boom():
        called["composio"] += 1
        raise AssertionError("should not call Composio for empty toolkits")

    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", _boom
    )

    await oauth_watcher.watch_oauth_and_bootstrap(
        user_id="u1", toolkits=[]
    )

    assert called["composio"] == 0
    assert stub_bootstrap["calls"] == []


@pytest.mark.asyncio
async def test_watcher_non_google_toolkit_marks_db_but_skips_bootstrap(
    db, monkeypatch, fast_intervals, stub_bootstrap, caplog
):
    """Connecting slack should mark the DB but NOT fire the gmail bootstrap.

    The biography algorithm is gmail-driven; running it for a slack-only
    connect would burn LLM cost for nothing.
    """
    items = [
        _FakeConnectedAccount(id="ca_s", status="ACTIVE", toolkit_slug="slack"),
    ]
    fake = _FakeComposio([items])
    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", lambda: fake
    )

    with caplog.at_level(logging.INFO, logger="backend.integrations.oauth_watcher"):
        await oauth_watcher.watch_oauth_and_bootstrap(
            user_id="u1",
            toolkits=["slack"],
            timeout_seconds=0,
            poll_interval=0,
        )

    # Bootstrap NOT fired — slack is not a gmail-bootstrap trigger.
    assert stub_bootstrap["calls"] == []
    # DB row mirrored as provider="composio"
    slack = await state.get_integration_status("u1", "composio", "slack")
    assert slack.status == "connected"
    assert slack.composio_connection_id == "ca_s"
    # Log explains why bootstrap was skipped
    assert any(
        "skipping bootstrap" in record.message.lower() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_watcher_mixed_google_and_other_marks_both_fires_bootstrap(
    db, monkeypatch, fast_intervals, stub_bootstrap
):
    """gmail + slack: gmail mirrors as google_gmail, slack mirrors as
    composio_slack, bootstrap fires because gmail is in the active set."""
    items = [
        _FakeConnectedAccount(id="ca_g", status="ACTIVE", toolkit_slug="gmail"),
        _FakeConnectedAccount(id="ca_s", status="ACTIVE", toolkit_slug="slack"),
    ]
    fake = _FakeComposio([items])
    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", lambda: fake
    )

    await oauth_watcher.watch_oauth_and_bootstrap(
        user_id="u1",
        toolkits=["gmail", "slack"],
        timeout_seconds=0,
        poll_interval=0,
    )

    assert stub_bootstrap["calls"] == ["u1"]
    gmail = await state.get_integration_status("u1", "google", "gmail")
    slack = await state.get_integration_status("u1", "composio", "slack")
    assert gmail.status == "connected"
    assert slack.status == "connected"


@pytest.mark.asyncio
async def test_back_compat_alias_exposed():
    """Older imports of watch_google_oauth_and_bootstrap still resolve."""
    assert (
        oauth_watcher.watch_google_oauth_and_bootstrap
        is oauth_watcher.watch_oauth_and_bootstrap
    )


# --- Hook integration tests ---


@pytest.mark.asyncio
async def test_post_tool_hook_spawns_oauth_watcher_for_connect_integration(
    monkeypatch
):
    """post_tool_hook should call _maybe_spawn_oauth_watcher with the
    tool_response for connect_integration tool calls."""
    from donna_runtime import hooks

    captured = {"calls": []}

    def _fake_spawn(tool_response):
        captured["calls"].append(tool_response)

    monkeypatch.setattr(hooks, "_maybe_spawn_oauth_watcher", _fake_spawn)

    tool_response = {
        "content": [{"type": "text", "text": "tap: https://x"}],
        "toolkits": ["gmail", "googlecalendar"],
        "urls": {
            "gmail": "https://x",
            "googlecalendar": "https://y",
        },
    }
    input_data = {
        "tool_name": "mcp__donna__connect_integration",
        "tool_input": {"toolkits": ["gmail", "googlecalendar"]},
        "tool_response": tool_response,
    }

    await hooks.post_tool_hook(input_data, "tool_use_42", None)

    assert captured["calls"] == [tool_response]


@pytest.mark.asyncio
async def test_post_tool_hook_does_not_spawn_for_other_tools(monkeypatch):
    from donna_runtime import hooks

    captured = {"calls": []}

    def _fake_spawn(tool_response):
        captured["calls"].append(tool_response)

    monkeypatch.setattr(hooks, "_maybe_spawn_oauth_watcher", _fake_spawn)

    input_data = {
        "tool_name": "mcp__donna__log_observation",
        "tool_input": {},
        "tool_response": {"content": [{"type": "text", "text": "ok"}]},
    }
    await hooks.post_tool_hook(input_data, "tool_use_43", None)

    assert captured["calls"] == []


def test_extract_connect_toolkits_prefers_explicit_field():
    """The hook should pick up the structured 'toolkits' field directly."""
    from donna_runtime.hooks import _extract_connect_toolkits

    out = _extract_connect_toolkits(
        {
            "toolkits": ["slack", "notion"],
            "urls": {"slack": "https://a", "notion": "https://b"},
        }
    )
    assert out == ["slack", "notion"]


def test_extract_connect_toolkits_falls_back_to_legacy_urls():
    """Legacy responses (urls keyed by friendly product names) still work."""
    from donna_runtime.hooks import _extract_connect_toolkits

    out = _extract_connect_toolkits(
        {"urls": {"gmail": "https://a", "calendar": "https://b", "drive": "https://c"}}
    )
    # Friendly aliases translated back to toolkit slugs
    assert out == ["gmail", "googlecalendar", "googledrive"]


def test_extract_connect_toolkits_returns_none_for_unrelated_payload():
    from donna_runtime.hooks import _extract_connect_toolkits

    assert _extract_connect_toolkits(None) is None
    assert _extract_connect_toolkits("just text") is None
    assert _extract_connect_toolkits({"something": "else"}) is None
