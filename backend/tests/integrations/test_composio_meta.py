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
