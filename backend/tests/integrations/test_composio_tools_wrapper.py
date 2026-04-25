from __future__ import annotations

import pytest


class _StubMeta:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.search_response = {"results": []}
        self.manage_response = {"results": {}}
        self.wait_response = {"results": {}}
        self.execute_response = {}

    async def search_tools(self, **kwargs):
        self.calls.append(("search_tools", kwargs))
        return self.search_response

    async def manage_connections(self, **kwargs):
        self.calls.append(("manage_connections", kwargs))
        return self.manage_response

    async def wait_for_connections(self, **kwargs):
        self.calls.append(("wait_for_connections", kwargs))
        return self.wait_response

    async def execute_tool(self, **kwargs):
        self.calls.append(("execute_tool", kwargs))
        return self.execute_response


@pytest.fixture
def stub_meta(monkeypatch):
    stub = _StubMeta()
    import backend.integrations.composio_meta as cm
    monkeypatch.setattr(cm, "search_tools", stub.search_tools)
    monkeypatch.setattr(cm, "manage_connections", stub.manage_connections)
    monkeypatch.setattr(cm, "wait_for_connections", stub.wait_for_connections)
    monkeypatch.setattr(cm, "execute_tool", stub.execute_tool)
    return stub


@pytest.fixture
def with_user_id(monkeypatch):
    monkeypatch.setattr("donna_runtime.tools._current_user_id", lambda: "u1")


@pytest.mark.asyncio
async def test_composio_search_tools_wrapper(stub_meta, with_user_id):
    from donna_runtime.tools import composio_search_tools

    stub_meta.search_response = {
        "results": [{"tool_slug": "GMAIL_LIST_MESSAGES"}]
    }
    out = await composio_search_tools.handler({"use_case": "read inbox"})
    assert "GMAIL_LIST_MESSAGES" in out["content"][0]["text"]
    assert stub_meta.calls == [
        ("search_tools", {"user_id": "u1", "use_case": "read inbox"}),
    ]


@pytest.mark.asyncio
async def test_composio_manage_connections_wrapper(stub_meta, with_user_id):
    from donna_runtime.tools import composio_manage_connections

    stub_meta.manage_response = {
        "results": {
            "gmail": {
                "status": "INITIATED",
                "redirect_url": "https://backend.composio.dev/g",
            },
        },
    }
    out = await composio_manage_connections.handler({"toolkits": ["gmail"]})
    text = out["content"][0]["text"]
    assert "https://backend.composio.dev/g" in text
    assert stub_meta.calls[0][0] == "manage_connections"
    assert stub_meta.calls[0][1] == {"user_id": "u1", "toolkits": ["gmail"]}


@pytest.mark.asyncio
async def test_composio_wait_for_connections_wrapper(stub_meta, with_user_id):
    from donna_runtime.tools import composio_wait_for_connections

    stub_meta.wait_response = {
        "results": {
            "gmail": {"status": "ACTIVE"},
            "googlecalendar": {"status": "ACTIVE"},
        },
    }
    out = await composio_wait_for_connections.handler({
        "toolkits": ["gmail", "googlecalendar"],
        "mode": "all",
    })
    text = out["content"][0]["text"]
    assert "ACTIVE" in text
    assert stub_meta.calls[0][1] == {
        "user_id": "u1",
        "toolkits": ["gmail", "googlecalendar"],
        "mode": "all",
        "timeout_seconds": 120,
    }


@pytest.mark.asyncio
async def test_composio_execute_tool_wrapper(stub_meta, with_user_id):
    from donna_runtime.tools import composio_execute_tool

    stub_meta.execute_response = {"items": [{"id": "m1"}]}
    out = await composio_execute_tool.handler({
        "tool_slug": "GMAIL_LIST_MESSAGES",
        "arguments": {"q": "newer_than:1d"},
    })
    text = out["content"][0]["text"]
    assert "m1" in text
    assert stub_meta.calls[0][1] == {
        "user_id": "u1",
        "tool_slug": "GMAIL_LIST_MESSAGES",
        "arguments": {"q": "newer_than:1d"},
    }
