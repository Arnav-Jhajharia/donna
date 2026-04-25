from __future__ import annotations

import pytest

from backend.integrations import composio_meta


class _FakeTools:
    def __init__(self, response):
        self.calls: list[tuple[str, dict]] = []
        self._response = response

    def execute(self, slug, *, user_id, arguments, **kwargs):
        self.calls.append(
            (
                slug,
                {
                    "user_id": user_id,
                    "arguments": arguments,
                    "kwargs": kwargs,
                },
            )
        )
        return self._response


class _FakeComposio:
    def __init__(self, response):
        self.tools = _FakeTools(response)


@pytest.fixture
def fake_composio(monkeypatch):
    instances: list[_FakeComposio] = []

    def _make(response):
        c = _FakeComposio(response)
        instances.append(c)
        monkeypatch.setattr(
            "backend.integrations.composio_meta._composio",
            lambda: c,
        )
        return c

    return _make


@pytest.mark.asyncio
async def test_search_tools_passes_use_case(fake_composio):
    c = fake_composio({"data": {"results": [{"tool_slug": "GMAIL_FETCH_MESSAGES"}]}})

    result = await composio_meta.search_tools(
        user_id="u1", use_case="read recent emails"
    )

    assert result == {"results": [{"tool_slug": "GMAIL_FETCH_MESSAGES"}]}
    slug, payload = c.tools.calls[0]
    assert slug == "COMPOSIO_SEARCH_TOOLS"
    assert payload["user_id"] == "u1"
    assert payload["arguments"] == {"use_case": "read recent emails"}
    assert payload["kwargs"].get("dangerously_skip_version_check") is True


@pytest.mark.asyncio
async def test_manage_connections_returns_redirect_urls(fake_composio):
    c = fake_composio({
        "data": {
            "results": {
                "gmail": {
                    "status": "initiated",
                    "redirect_url": "https://backend.composio.dev/x",
                    "auth_config_id": "ac_gmail",
                },
            },
        },
    })

    result = await composio_meta.manage_connections(
        user_id="u1", toolkits=["gmail"]
    )

    assert result["results"]["gmail"]["redirect_url"] == (
        "https://backend.composio.dev/x"
    )
    assert result["results"]["gmail"]["status"] == "initiated"
    assert result["results"]["gmail"]["auth_config_id"] == "ac_gmail"
    assert "connected_account_id" not in result["results"]["gmail"]
    slug, payload = c.tools.calls[0]
    assert slug == "COMPOSIO_MANAGE_CONNECTIONS"
    assert payload["arguments"] == {"toolkits": ["gmail"]}
    assert payload["kwargs"].get("dangerously_skip_version_check") is True


@pytest.mark.asyncio
async def test_wait_for_connections_passes_mode_and_timeout(fake_composio):
    c = fake_composio({
        "data": {
            "message": "Active: gmail.",
            "results": {
                "gmail": {
                    "toolkit": "gmail",
                    "status": "active",
                    "connected_account_id": "ca_x",
                },
            },
        },
    })

    result = await composio_meta.wait_for_connections(
        user_id="u1",
        toolkits=["gmail"],
        mode="all",
        timeout_seconds=120,
    )

    assert result["results"]["gmail"]["status"] == "active"
    assert result["results"]["gmail"]["connected_account_id"] == "ca_x"
    slug, payload = c.tools.calls[0]
    assert slug == "COMPOSIO_WAIT_FOR_CONNECTIONS"
    assert payload["arguments"]["toolkits"] == ["gmail"]
    assert payload["arguments"]["mode"] == "all"
    assert payload["arguments"]["timeout_seconds"] == 120
    assert payload["kwargs"].get("dangerously_skip_version_check") is True


@pytest.mark.asyncio
async def test_execute_tool_passes_args_through(fake_composio):
    c = fake_composio({"data": {"items": []}})

    result = await composio_meta.execute_tool(
        user_id="u1",
        tool_slug="GMAIL_LIST_MESSAGES",
        arguments={"q": "newer_than:1d", "max_results": 10},
    )

    assert result == {"items": []}
    slug, payload = c.tools.calls[0]
    assert slug == "GMAIL_LIST_MESSAGES"
    assert payload["arguments"] == {"q": "newer_than:1d", "max_results": 10}
    assert payload["kwargs"].get("dangerously_skip_version_check") is True


# --- OAuth chain helpers ---


class _FakeConnectionRequest:
    def __init__(self, *, id: str, redirect_url: str, status: str = "INITIATED"):
        self.id = id
        self.redirect_url = redirect_url
        self.status = status


class _FakeConnectedAccounts:
    """Records each initiate() call. Generates a unique redirect URL per call
    so tests can verify the chain wiring."""

    def __init__(self):
        self.calls: list[dict] = []
        self._counter = 0

    def initiate(self, user_id, auth_config_id, *, callback_url=None):
        self._counter += 1
        idx = self._counter
        req = _FakeConnectionRequest(
            id=f"ca_{auth_config_id}",
            redirect_url=f"https://composio.dev/redirect/{auth_config_id}/{idx}",
        )
        self.calls.append(
            {
                "user_id": user_id,
                "auth_config_id": auth_config_id,
                "callback_url": callback_url,
                "returned_redirect_url": req.redirect_url,
                "returned_id": req.id,
            }
        )
        return req


class _FakeAuthConfigItem:
    def __init__(self, *, id: str, toolkit_slug: str | None):
        self.id = id

        class _T:
            slug = toolkit_slug

        self.toolkit = _T() if toolkit_slug is not None else None


class _FakeAuthConfigs:
    def __init__(self, items):
        self._items = items
        self.calls: int = 0

    def list(self):
        self.calls += 1

        class _Listing:
            pass

        listing = _Listing()
        listing.items = self._items
        return listing


class _FakeComposioFull:
    def __init__(self, *, auth_configs_items=None):
        self.connected_accounts = _FakeConnectedAccounts()
        self.auth_configs = _FakeAuthConfigs(auth_configs_items or [])
        self.tools = _FakeTools({"data": {}})


@pytest.fixture
def fake_composio_full(monkeypatch):
    instances: list[_FakeComposioFull] = []

    def _make(*, auth_configs_items=None):
        c = _FakeComposioFull(auth_configs_items=auth_configs_items)
        instances.append(c)
        monkeypatch.setattr(
            "backend.integrations.composio_meta._composio",
            lambda: c,
        )
        return c

    return _make


@pytest.mark.asyncio
async def test_initiate_oauth_chain_links_callbacks_in_reverse(fake_composio_full):
    c = fake_composio_full()

    toolkit_to_auth_config = {
        "gmail": "ac_gmail",
        "googlecalendar": "ac_cal",
        "googledrive": "ac_drive",
    }

    result = await composio_meta.initiate_oauth_chain(
        user_id="u1",
        toolkit_to_auth_config=toolkit_to_auth_config,
        final_callback_url="https://platform.composio.dev/dashboard",
    )

    # 3 toolkits -> 3 calls in REVERSE order (drive first, gmail last)
    assert len(c.connected_accounts.calls) == 3
    call_order = [c.connected_accounts.calls[i]["auth_config_id"] for i in range(3)]
    assert call_order == ["ac_drive", "ac_cal", "ac_gmail"]

    # Drive's callback is the final dashboard URL
    drive_call = c.connected_accounts.calls[0]
    cal_call = c.connected_accounts.calls[1]
    gmail_call = c.connected_accounts.calls[2]
    assert drive_call["callback_url"] == "https://platform.composio.dev/dashboard"

    # Calendar's callback is drive's redirect_url
    assert cal_call["callback_url"] == drive_call["returned_redirect_url"]

    # Gmail's callback is calendar's redirect_url
    assert gmail_call["callback_url"] == cal_call["returned_redirect_url"]

    # Returned chain is in INPUT order: gmail, googlecalendar, googledrive
    chain = result["chain"]
    assert [entry["toolkit"] for entry in chain] == [
        "gmail",
        "googlecalendar",
        "googledrive",
    ]
    assert [entry["auth_config_id"] for entry in chain] == [
        "ac_gmail",
        "ac_cal",
        "ac_drive",
    ]
    # connected_account_id propagated
    assert chain[0]["connected_account_id"] == "ca_ac_gmail"
    assert chain[1]["connected_account_id"] == "ca_ac_cal"
    assert chain[2]["connected_account_id"] == "ca_ac_drive"
    # Each chain entry's redirect_url matches what initiate returned
    assert chain[0]["redirect_url"] == gmail_call["returned_redirect_url"]
    assert chain[1]["redirect_url"] == cal_call["returned_redirect_url"]
    assert chain[2]["redirect_url"] == drive_call["returned_redirect_url"]

    # first_url is the FIRST toolkit's redirect_url (gmail)
    assert result["first_url"] == chain[0]["redirect_url"]


@pytest.mark.asyncio
async def test_initiate_oauth_chain_single_toolkit(fake_composio_full):
    c = fake_composio_full()

    result = await composio_meta.initiate_oauth_chain(
        user_id="u1",
        toolkit_to_auth_config={"gmail": "ac_gmail"},
    )

    assert len(c.connected_accounts.calls) == 1
    call = c.connected_accounts.calls[0]
    # Single toolkit's callback is the default dashboard URL
    assert call["callback_url"] == "https://platform.composio.dev/dashboard"
    assert result["first_url"] == call["returned_redirect_url"]
    assert len(result["chain"]) == 1


@pytest.mark.asyncio
async def test_resolve_auth_configs_picks_from_existing(fake_composio_full):
    c = fake_composio_full(
        auth_configs_items=[
            _FakeAuthConfigItem(id="ac_gmail_old", toolkit_slug="gmail"),
            _FakeAuthConfigItem(id="ac_gmail_new", toolkit_slug="gmail"),
            _FakeAuthConfigItem(id="ac_cal", toolkit_slug="googlecalendar"),
        ]
    )

    out = await composio_meta.resolve_auth_configs(
        toolkits=["gmail", "googlecalendar"], user_id="u1"
    )

    assert c.auth_configs.calls == 1
    # last-write-wins for duplicates -> most recent
    assert out == {"gmail": "ac_gmail_new", "googlecalendar": "ac_cal"}
    # input order preserved
    assert list(out.keys()) == ["gmail", "googlecalendar"]


@pytest.mark.asyncio
async def test_resolve_auth_configs_falls_back_to_manage_for_missing(
    fake_composio_full, monkeypatch
):
    fake_composio_full(
        auth_configs_items=[
            _FakeAuthConfigItem(id="ac_gmail", toolkit_slug="gmail"),
        ]
    )

    captured = {}

    async def _fake_manage(*, user_id, toolkits):
        captured["user_id"] = user_id
        captured["toolkits"] = toolkits
        return {
            "results": {
                "googledrive": {
                    "status": "initiated",
                    "redirect_url": "https://x",
                    "auth_config_id": "ac_drive_new",
                },
            }
        }

    monkeypatch.setattr(
        composio_meta, "manage_connections", _fake_manage
    )

    out = await composio_meta.resolve_auth_configs(
        toolkits=["gmail", "googledrive"], user_id="u1"
    )

    assert captured["toolkits"] == ["googledrive"]
    assert out == {"gmail": "ac_gmail", "googledrive": "ac_drive_new"}
    # Original toolkit order preserved
    assert list(out.keys()) == ["gmail", "googledrive"]


@pytest.mark.asyncio
async def test_resolve_auth_configs_omits_toolkit_when_manage_returns_no_id(
    fake_composio_full, monkeypatch
):
    fake_composio_full(auth_configs_items=[])

    async def _fake_manage(*, user_id, toolkits):
        return {"results": {"googledrive": {"status": "failed"}}}

    monkeypatch.setattr(composio_meta, "manage_connections", _fake_manage)

    out = await composio_meta.resolve_auth_configs(
        toolkits=["googledrive"], user_id="u1"
    )

    assert out == {}


