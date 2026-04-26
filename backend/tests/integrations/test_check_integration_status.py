"""Tests for backend.memory.tools.check_integration_status.

Covers:
- Composio truth + local DB merged into a single per-toolkit view
- Reconcile: ACTIVE on Composio + pending locally -> upgrades to connected
- Reconcile: EXPIRED on Composio + connected locally -> marks revoked
- Composio unreachable -> falls back to local mirror
- Filter by toolkits[] respected; explicit unknown toolkit returned as 'absent'
- Summary string is parseable + stable
"""
from __future__ import annotations

import pytest

from backend.integrations import state
from backend.memory.tools.check_integration_status import (
    check_integration_status,
)


class _FakeCA:
    def __init__(self, *, id: str, status: str, slug: str):
        self.id = id
        self.status = status

        class _T:
            pass

        self.toolkit = _T()
        self.toolkit.slug = slug


class _FakeListing:
    def __init__(self, items):
        self.items = items


class _FakeAccounts:
    def __init__(self, items):
        self.items_seq = items
        self.calls = 0

    def list(self, *, user_ids=None, **_):
        self.calls += 1
        return _FakeListing(self.items_seq)


class _FakeComposio:
    def __init__(self, items):
        self.connected_accounts = _FakeAccounts(items)


@pytest.fixture
def stub_composio(monkeypatch):
    """Plug a fake Composio client; tests can mutate `.items` per case."""
    holder = {"items": []}

    def _factory():
        return _FakeComposio(holder["items"])

    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", _factory
    )
    return holder


@pytest.mark.asyncio
async def test_status_merges_composio_and_local(db, stub_composio):
    """Composio reports gmail ACTIVE + slack EXPIRED; local has gmail
    pending + nothing for slack. After reconcile both rows surface
    correctly and the local DB has been brought up to date."""
    stub_composio["items"] = [
        _FakeCA(id="ca_g", status="ACTIVE", slug="gmail"),
        _FakeCA(id="ca_s", status="EXPIRED", slug="slack"),
    ]
    await state.upsert_pending("u1", "google", "gmail")

    res = await check_integration_status(user_id="u1")

    assert "gmail" in res["toolkits"]
    assert res["toolkits"]["gmail"]["status"] == "connected"
    assert res["toolkits"]["gmail"]["connected_account_id"] == "ca_g"
    # slack appeared on Composio but had no local row — reconcile didn't
    # invent one (only flips connected/revoked transitions). Local stays
    # absent.
    assert res["toolkits"]["slack"]["status"] == "absent"
    assert "gmail=on" in res["summary"]
    assert "slack=" in res["summary"]


@pytest.mark.asyncio
async def test_reconcile_upgrades_pending_to_connected(
    db, stub_composio, monkeypatch
):
    """Most important case: watcher missed the OAuth completion, but
    check_integration_status picks it up by reading Composio truth.
    Also: when a google toolkit flips, we self-heal by spawning the
    bootstrap pipeline that the missed watcher would have fired."""
    stub_composio["items"] = [
        _FakeCA(id="ca_new", status="ACTIVE", slug="googlecalendar"),
    ]
    await state.upsert_pending("u1", "google", "calendar")

    # Capture bootstrap spawn — the auto-heal path should fire it.
    bootstrap_calls = {"count": 0}

    async def _fake_bootstrap(user_id):
        bootstrap_calls["count"] += 1
        return {"status": "completed"}

    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async", _fake_bootstrap
    )

    # Pre-state: pending
    pre = await state.get_integration_status("u1", "google", "calendar")
    assert pre.status == "pending"

    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["googlecalendar"]["status"] == "connected"
    assert res["toolkits"]["googlecalendar"]["connected_account_id"] == "ca_new"

    # Post-state: DB upgraded
    post = await state.get_integration_status("u1", "google", "calendar")
    assert post.status == "connected"
    assert post.composio_connection_id == "ca_new"

    # Bootstrap spawned (asyncio.create_task — give the loop a tick)
    import asyncio
    await asyncio.sleep(0)
    assert bootstrap_calls["count"] == 1


@pytest.mark.asyncio
async def test_reconcile_does_not_spawn_bootstrap_for_non_google(
    db, stub_composio, monkeypatch
):
    """Slack going ACTIVE should reconcile + mark connected but NOT fire
    the gmail-driven bootstrap (the algorithm is gmail-specific)."""
    stub_composio["items"] = [
        _FakeCA(id="ca_s", status="ACTIVE", slug="slack"),
    ]
    await state.upsert_pending("u1", "composio", "slack")

    bootstrap_calls = {"count": 0}

    async def _fake_bootstrap(user_id):
        bootstrap_calls["count"] += 1
        return {"status": "completed"}

    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async", _fake_bootstrap
    )

    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["slack"]["status"] == "connected"
    import asyncio
    await asyncio.sleep(0)
    assert bootstrap_calls["count"] == 0


@pytest.mark.asyncio
async def test_reconcile_idempotent_skips_bootstrap_when_already_connected(
    db, stub_composio, monkeypatch
):
    """Calling check_integration_status when the row is ALREADY connected
    should not spawn bootstrap (no flip happened)."""
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_g"
    )

    stub_composio["items"] = [
        _FakeCA(id="ca_g", status="ACTIVE", slug="gmail"),
    ]

    bootstrap_calls = {"count": 0}

    async def _fake_bootstrap(user_id):
        bootstrap_calls["count"] += 1
        return {"status": "completed"}

    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async", _fake_bootstrap
    )

    await check_integration_status(user_id="u1")
    import asyncio
    await asyncio.sleep(0)
    # No flip -> no bootstrap fire (the 1h dedupe in run_bootstrap_async
    # would catch a redundant call too, but we don't even get there).
    assert bootstrap_calls["count"] == 0


@pytest.mark.asyncio
async def test_reconcile_marks_revoked_when_composio_says_expired(
    db, stub_composio
):
    """Local says connected, Composio now says EXPIRED — local downgrades
    to revoked so the [INTEGRATIONS] block stops claiming green."""
    await state.upsert_pending("u1", "composio", "slack")
    await state.mark_connected(
        "u1", "composio", "slack", connection_id="ca_old"
    )

    stub_composio["items"] = [
        _FakeCA(id="ca_old", status="EXPIRED", slug="slack"),
    ]

    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["slack"]["status"] == "revoked"

    post = await state.get_integration_status("u1", "composio", "slack")
    assert post.status == "revoked"


@pytest.mark.asyncio
async def test_composio_unreachable_falls_back_to_local(db, monkeypatch):
    """If the Composio API call raises, we still return the local mirror
    rather than crashing or hiding state from Donna."""
    def _boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "backend.integrations.composio_meta._composio", _boom
    )

    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_local"
    )

    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["gmail"]["status"] == "connected"
    assert res["toolkits"]["gmail"]["connected_account_id"] == "ca_local"


@pytest.mark.asyncio
async def test_filter_returns_absent_for_unknown_explicit_toolkit(
    db, stub_composio
):
    """Asking specifically about 'notion' when there's nothing on file
    returns 'absent' (not nothing) so Donna can answer honestly."""
    res = await check_integration_status(user_id="u1", toolkits=["notion"])
    assert "notion" in res["toolkits"]
    assert res["toolkits"]["notion"]["status"] == "absent"
    assert "notion=not_connected" in res["summary"]


@pytest.mark.asyncio
async def test_filter_narrows_results(db, stub_composio):
    """Passing toolkits=[gmail] hides slack from the response even when
    both are on file."""
    stub_composio["items"] = [
        _FakeCA(id="ca_g", status="ACTIVE", slug="gmail"),
        _FakeCA(id="ca_s", status="ACTIVE", slug="slack"),
    ]
    await state.upsert_pending("u1", "google", "gmail")
    await state.upsert_pending("u1", "composio", "slack")

    res = await check_integration_status(user_id="u1", toolkits=["gmail"])
    assert set(res["toolkits"].keys()) == {"gmail"}


@pytest.mark.asyncio
async def test_empty_when_user_has_no_integrations(db, stub_composio):
    """Brand new user — no rows anywhere — returns empty toolkits dict."""
    res = await check_integration_status(user_id="brand-new-user")
    assert res["toolkits"] == {}
    assert res["summary"] == "no integrations on file"


@pytest.mark.asyncio
async def test_prefers_active_over_initiated_when_duplicate_accounts(
    db, stub_composio, monkeypatch
):
    """Real-world failure mode: re-initiating OAuth creates a SECOND
    connected_account row for the same toolkit. Composio returns both —
    one ACTIVE, one INITIATED. We must report ACTIVE and reconcile to
    connected; otherwise Donna falsely reports the toolkit as 'not
    connected' when it actually is."""
    stub_composio["items"] = [
        # Order matters: INITIATED returned BEFORE ACTIVE in some
        # listings, AFTER in others. The fix must be order-independent.
        _FakeCA(id="ca_initiated", status="INITIATED", slug="gmail"),
        _FakeCA(id="ca_active", status="ACTIVE", slug="gmail"),
    ]
    await state.upsert_pending("u1", "google", "gmail")

    bootstrap_calls = {"count": 0}

    async def _fake_bootstrap(user_id):
        bootstrap_calls["count"] += 1
        return {"status": "completed"}

    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async", _fake_bootstrap
    )

    res = await check_integration_status(user_id="u1")
    # ACTIVE wins despite being later in the listing
    assert res["toolkits"]["gmail"]["status"] == "connected"
    assert res["toolkits"]["gmail"]["connected_account_id"] == "ca_active"
    # And the auto-bootstrap fired since the row flipped
    import asyncio
    await asyncio.sleep(0)
    assert bootstrap_calls["count"] == 1


@pytest.mark.asyncio
async def test_prefers_active_when_active_appears_first(
    db, stub_composio
):
    """Order-independence in the other direction."""
    stub_composio["items"] = [
        _FakeCA(id="ca_active", status="ACTIVE", slug="gmail"),
        _FakeCA(id="ca_initiated", status="INITIATED", slug="gmail"),
    ]
    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["gmail"]["connected_account_id"] == "ca_active"


@pytest.mark.asyncio
async def test_reconcile_fires_immediate_connected_ping_for_any_toolkit(
    db, stub_composio, monkeypatch
):
    """The big real-world failure: watcher dies + webhook 404s. The ONLY
    path that picks up the connection is reconcile. It MUST fire the
    immediate-connected ping or the user gets total silence."""
    stub_composio["items"] = [
        _FakeCA(id="ca_s", status="ACTIVE", slug="slack"),
    ]
    await state.upsert_pending("u1", "composio", "slack")

    notify_calls: list = []

    async def _fake_notify(user_id, toolkits, *, stage=None, **_kw):
        notify_calls.append({
            "user_id": user_id, "toolkits": list(toolkits), "stage": stage,
        })
        return {"status": "sent"}

    monkeypatch.setattr(
        "backend.integrations.notify.notify_integration_complete",
        _fake_notify,
    )

    res = await check_integration_status(user_id="u1")
    assert res["toolkits"]["slack"]["status"] == "connected"

    import asyncio
    await asyncio.sleep(0)
    assert len(notify_calls) == 1
    assert notify_calls[0]["toolkits"] == ["slack"]
    assert notify_calls[0]["stage"] == "connected"


@pytest.mark.asyncio
async def test_reconcile_fires_notify_for_google_too(
    db, stub_composio, monkeypatch
):
    """Google toolkits get the immediate-confirm ping AND a separate
    bootstrap-completion ping later. This test verifies the immediate
    one fires from the reconcile path (the bootstrap path is its own
    test in test_bootstrap_idempotency.py)."""
    stub_composio["items"] = [
        _FakeCA(id="ca_g", status="ACTIVE", slug="gmail"),
    ]
    await state.upsert_pending("u1", "google", "gmail")

    notify_calls: list = []

    async def _fake_notify(user_id, toolkits, *, stage=None, **_kw):
        notify_calls.append({"toolkits": list(toolkits), "stage": stage})
        return {"status": "sent"}

    async def _fake_bootstrap(user_id):
        return {"status": "completed"}

    monkeypatch.setattr(
        "backend.integrations.notify.notify_integration_complete",
        _fake_notify,
    )
    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async", _fake_bootstrap
    )

    await check_integration_status(user_id="u1")
    import asyncio
    await asyncio.sleep(0)

    assert len(notify_calls) == 1
    assert notify_calls[0]["toolkits"] == ["gmail"]
    assert notify_calls[0]["stage"] == "connected"


@pytest.mark.asyncio
async def test_reconcile_skips_notify_when_no_flip(
    db, stub_composio, monkeypatch
):
    """Already-connected row with matching ACTIVE on Composio = no flip,
    no notify. Otherwise we'd ping every time per-turn reconcile runs."""
    await state.upsert_pending("u1", "composio", "slack")
    await state.mark_connected(
        "u1", "composio", "slack", connection_id="ca_s"
    )
    stub_composio["items"] = [
        _FakeCA(id="ca_s", status="ACTIVE", slug="slack"),
    ]

    notify_calls: list = []

    async def _fake_notify(user_id, toolkits, *, stage=None, **_kw):
        notify_calls.append({"toolkits": list(toolkits)})
        return {"status": "sent"}

    monkeypatch.setattr(
        "backend.integrations.notify.notify_integration_complete",
        _fake_notify,
    )

    await check_integration_status(user_id="u1")
    import asyncio
    await asyncio.sleep(0)
    assert notify_calls == []


@pytest.mark.asyncio
async def test_prefers_initiated_over_expired(db, stub_composio):
    """A re-initiation after expiry: INITIATED beats EXPIRED so we don't
    mark a row 'revoked' just because the old account is still around."""
    stub_composio["items"] = [
        _FakeCA(id="ca_old", status="EXPIRED", slug="gmail"),
        _FakeCA(id="ca_new", status="INITIATED", slug="gmail"),
    ]
    await state.upsert_pending("u1", "google", "gmail")

    res = await check_integration_status(user_id="u1")
    # Local row stays pending (INITIATED on Composio means OAuth in
    # flight; we don't flip to revoked).
    assert res["toolkits"]["gmail"]["status"] == "pending"
