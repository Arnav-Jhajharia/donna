# Composio Meta-Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace our hand-rolled per-toolkit OAuth wrapper with Composio's meta-tools (`COMPOSIO_MANAGE_CONNECTIONS` + `COMPOSIO_WAIT_FOR_CONNECTIONS`), so Donna can connect ANY Composio-supported integration in one turn flow without our webhook handler or reconcile script.

**Architecture:** Add four thin Donna-tool wrappers around Composio's meta-tools (`composio_search_tools`, `composio_manage_connections`, `composio_wait_for_connections`, `composio_execute_tool`). Refactor `connect_integration` to delegate to `composio_manage_connections` internally — same Donna-facing interface, drastically simpler implementation. Keep typed Gmail/Calendar tools (`list_gmail_recent`, `read_gmail_thread`, `list_calendar`) for performance and the bootstrap pipeline. The meta-tools become Donna's escape hatch for any-other-integration.

**Tech Stack:** Python 3.13, `composio>=0.11` SDK (`composio.tools.execute(slug, ...)`), Claude Agent SDK MCP tools, pytest+pytest-asyncio for tests.

---

## File Structure

**Files created:**
- `backend/integrations/composio_meta.py` — thin async wrappers around `composio.tools.execute("COMPOSIO_*", ...)` calls. Single responsibility: shape the SDK's sync exec into our async surface.
- `backend/tests/integrations/test_composio_meta.py` — unit tests with monkey-patched `composio.tools.execute`.
- `backend/tests/integrations/test_composio_tools_wrapper.py` — tests for the Donna-tool wrappers (search/manage/wait/execute).

**Files modified:**
- `backend/memory/tools/connect_integration.py` — body replaced; delegates to `composio_meta.manage_connections`.
- `donna_runtime/tools.py` — add 4 `@tool` definitions exposing the meta-tools (search, manage, wait, execute). Add to `DONNA_TOOLS`.
- `donna_runtime/config.py` — add the 4 new tool slugs to `ALLOWED_TOOLS`.
- `donna_runtime/prompt.py` — extend `# INTEGRATIONS` section with the connect→wait pattern.
- `backend/tests/integrations/test_connect_integration_tool.py` — update existing tests to monkey-patch the new internal call site.

---

### Task 1: Spike — verify meta-tools work via Python SDK

**Files:**
- Create: `scripts/probe_composio_meta.py` (throwaway after task)

- [ ] **Step 1: Write the probe script**

```python
"""One-shot probe to confirm we can invoke COMPOSIO meta-tools from the SDK.
Throwaway — delete after Task 1 is green."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from donna_runtime.env import load_dotenv
load_dotenv()

from composio import Composio

USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"


def main() -> int:
    c = Composio()

    # 1. Search for a calendar tool
    res = c.tools.execute(
        "COMPOSIO_SEARCH_TOOLS",
        user_id=USER_ID,
        arguments={"use_case": "fetch calendar events for today"},
    )
    print("SEARCH_TOOLS keys:", list(res.get("data", {}).keys()))
    print("SEARCH_TOOLS top-level:", list(res.keys()))

    # 2. Inspect the manage-connections schema
    res = c.tools.execute(
        "COMPOSIO_MANAGE_CONNECTIONS",
        user_id=USER_ID,
        arguments={"toolkits": ["gmail"]},
    )
    print()
    print("MANAGE_CONNECTIONS result top-level:", list(res.keys()))
    print("MANAGE_CONNECTIONS data preview:",
          json.dumps(res.get("data", {}), indent=2)[:800])

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python scripts/probe_composio_meta.py
```

Expected: prints non-empty `data` dicts from both calls. The MANAGE_CONNECTIONS result should include redirect URLs and a session id we can pass to WAIT_FOR_CONNECTIONS.

- [ ] **Step 3: Document the actual response shapes inline in the plan**

Edit Task 2's helper module template below to match the real response shapes returned by the probe. Specifically:
- Note where the redirect URL lives (e.g. `data.results.<toolkit>.redirect_url`)
- Note the connection-id field name (`connected_account_id` based on the playground transcript)
- Note whether `session_id` is required for WAIT_FOR_CONNECTIONS (the playground showed `"session_id": "unit"`)

- [ ] **Step 4: Delete the probe**

```bash
rm scripts/probe_composio_meta.py
```

No commit — this task is throwaway-spike-only.

---

### Task 2: `composio_meta` helper module

**Files:**
- Create: `backend/integrations/composio_meta.py`
- Test: `backend/tests/integrations/test_composio_meta.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_composio_meta.py
from __future__ import annotations

import pytest

from backend.integrations import composio_meta


class _FakeTools:
    def __init__(self, response):
        self.calls: list[tuple[str, dict]] = []
        self._response = response

    def execute(self, slug, *, user_id, arguments):
        self.calls.append((slug, {"user_id": user_id, "arguments": arguments}))
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
    assert c.tools.calls == [(
        "COMPOSIO_SEARCH_TOOLS",
        {"user_id": "u1", "arguments": {"use_case": "read recent emails"}},
    )]


@pytest.mark.asyncio
async def test_manage_connections_returns_redirect_urls(fake_composio):
    c = fake_composio({
        "data": {
            "results": {
                "gmail": {
                    "status": "INITIATED",
                    "redirect_url": "https://backend.composio.dev/x",
                    "connected_account_id": "ca_new",
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
    slug, payload = c.tools.calls[0]
    assert slug == "COMPOSIO_MANAGE_CONNECTIONS"
    assert payload["arguments"] == {"toolkits": ["gmail"]}


@pytest.mark.asyncio
async def test_wait_for_connections_passes_mode_and_timeout(fake_composio):
    c = fake_composio({
        "data": {
            "message": "Active: gmail.",
            "results": {
                "gmail": {
                    "toolkit": "gmail",
                    "status": "ACTIVE",
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

    assert result["results"]["gmail"]["status"] == "ACTIVE"
    slug, payload = c.tools.calls[0]
    assert slug == "COMPOSIO_WAIT_FOR_CONNECTIONS"
    assert payload["arguments"]["toolkits"] == ["gmail"]
    assert payload["arguments"]["mode"] == "all"
    assert payload["arguments"]["timeout_seconds"] == 120


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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_composio_meta.py -v
```

Expected: `ImportError: cannot import name 'composio_meta'`.

- [ ] **Step 3: Implement `composio_meta`**

```python
# backend/integrations/composio_meta.py
"""Thin async wrappers around Composio's meta-tools.

Composio's COMPOSIO_* meta-tools handle the agent-side of integrations:
discovery (search), connection lifecycle (manage + wait), and generic
execute. We expose them as Donna tools so any toolkit composio supports
becomes connectable without per-provider code.

The Composio Python SDK is sync — we wrap each call in a coroutine for
the agent runtime, but no thread offload is needed (the calls are short
HTTP round-trips except WAIT_FOR_CONNECTIONS, which the SDK polls
internally and we should NOT block the event loop on).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)


def _composio():
    """Lazy import so test monkeypatches at this module's name take effect."""
    from composio import Composio
    return Composio()


def _data(response: dict | None) -> dict:
    """Composio wraps everything in `{data: {...}, error, successful}`. We
    only ever care about `data` — return it (or empty dict on missing)."""
    if not response:
        return {}
    return response.get("data") or {}


async def search_tools(*, user_id: str, use_case: str) -> dict:
    """COMPOSIO_SEARCH_TOOLS — discover the right tool by use-case."""
    composio = _composio()
    return _data(composio.tools.execute(
        "COMPOSIO_SEARCH_TOOLS",
        user_id=user_id,
        arguments={"use_case": use_case},
    ))


async def manage_connections(*, user_id: str, toolkits: list[str]) -> dict:
    """COMPOSIO_MANAGE_CONNECTIONS — initiate OAuth for missing toolkits.

    Returns dict with `results.<toolkit>.{status, redirect_url, ...}`.
    Idempotent at Composio: already-active toolkits are skipped.
    """
    composio = _composio()
    return _data(composio.tools.execute(
        "COMPOSIO_MANAGE_CONNECTIONS",
        user_id=user_id,
        arguments={"toolkits": list(toolkits)},
    ))


async def wait_for_connections(
    *,
    user_id: str,
    toolkits: list[str],
    mode: Literal["all", "any"] = "all",
    timeout_seconds: int = 120,
) -> dict:
    """COMPOSIO_WAIT_FOR_CONNECTIONS — block until OAuth completes.

    `mode="all"` waits for every toolkit; `mode="any"` returns once one is
    ACTIVE. The SDK polls Composio internally; the call returns when the
    condition is met or the timeout expires.
    """
    composio = _composio()
    return _data(composio.tools.execute(
        "COMPOSIO_WAIT_FOR_CONNECTIONS",
        user_id=user_id,
        arguments={
            "toolkits": list(toolkits),
            "mode": mode,
            "timeout_seconds": timeout_seconds,
        },
    ))


async def execute_tool(
    *, user_id: str, tool_slug: str, arguments: dict[str, Any]
) -> dict:
    """Generic Composio tool execution. Use for one-off integration calls
    that don't have a typed Donna tool yet."""
    composio = _composio()
    return _data(composio.tools.execute(
        tool_slug,
        user_id=user_id,
        arguments=arguments,
    ))
```

- [ ] **Step 4: Run — expect 4/4 pass**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_composio_meta.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/composio_meta.py \
        backend/tests/integrations/test_composio_meta.py
git commit -m "feat(integrations): composio meta-tools helper"
```

---

### Task 3: Donna-tool wrappers for the four meta-tools

**Files:**
- Modify: `donna_runtime/tools.py`
- Modify: `donna_runtime/config.py`
- Test: `backend/tests/integrations/test_composio_tools_wrapper.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_composio_tools_wrapper.py
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
```

- [ ] **Step 2: Run — expect ImportError on the four wrapper names**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_composio_tools_wrapper.py -v
```

- [ ] **Step 3: Add the four `@tool` wrappers in `donna_runtime/tools.py`**

Insert immediately AFTER the existing `read_gmail_thread` definition (around line 320):

```python
@tool(
    "composio_search_tools",
    "Discover the right Composio tool slug for an integration use-case "
    "you don't already have a typed wrapper for. Use when the user asks "
    "for an action against a connected SaaS provider (slack, notion, "
    "linear, etc.) and you don't recognize the right tool name. Do NOT "
    "use for gmail or calendar — those have typed tools "
    "(list_gmail_recent, read_gmail_thread, list_calendar). Returns a "
    "ranked list of tool slugs with descriptions; pass the chosen slug "
    "to composio_execute_tool.",
    {
        "type": "object",
        "properties": {
            "use_case": {
                "type": "string",
                "description": "Plain-language description of what you want to do.",
            },
        },
        "required": ["use_case"],
    },
)
@traceable(name="donna.tool.composio_search_tools", run_type="tool")
async def composio_search_tools(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot search: no user_id in scope.")
    use_case = str(args.get("use_case") or "").strip()
    if not use_case:
        return text_content("Cannot search: 'use_case' is required.")

    res = await composio_meta.search_tools(user_id=user_id, use_case=use_case)
    import json as _json
    return text_content(_json.dumps(res, indent=2))


@tool(
    "composio_manage_connections",
    "Initiate OAuth for one or more Composio toolkits. Returns a redirect "
    "URL per toolkit that the user must tap to consent. Idempotent: "
    "already-connected toolkits are skipped silently. Use when the user "
    "asks to connect a SaaS provider, or you need a tool whose toolkit "
    "is not yet active. Pair with composio_wait_for_connections in the "
    "next turn (after the user has tapped the URLs) to confirm completion.",
    {
        "type": "object",
        "properties": {
            "toolkits": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Composio toolkit slugs (e.g. ['gmail', "
                               "'googlecalendar', 'slack', 'notion']).",
            },
        },
        "required": ["toolkits"],
    },
)
@traceable(name="donna.tool.composio_manage_connections", run_type="tool")
async def composio_manage_connections(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot connect: no user_id in scope.")
    raw = args.get("toolkits") or []
    toolkits = [str(t).strip() for t in raw if str(t).strip()]
    if not toolkits:
        return text_content("Cannot connect: 'toolkits' is required.")

    res = await composio_meta.manage_connections(
        user_id=user_id, toolkits=toolkits
    )
    lines = []
    for slug, payload in (res.get("results") or {}).items():
        status = (payload or {}).get("status", "?")
        url = (payload or {}).get("redirect_url")
        if status == "ACTIVE":
            lines.append(f"{slug}: already connected")
        elif url:
            lines.append(f"{slug}: tap to connect {url}")
        else:
            lines.append(f"{slug}: status={status}")
    return text_content("\n".join(lines) or "no toolkits returned")


@tool(
    "composio_wait_for_connections",
    "Block until specified Composio toolkits finish OAuth (or timeout). "
    "Use after composio_manage_connections, on a follow-up turn, to "
    "confirm the user completed the consent flow before executing tools "
    "that depend on those toolkits. mode='all' waits for every toolkit; "
    "mode='any' returns once one is ACTIVE. Default timeout 120s.",
    {
        "type": "object",
        "properties": {
            "toolkits": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "mode": {"type": "string", "enum": ["all", "any"]},
            "timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 600},
        },
        "required": ["toolkits"],
    },
)
@traceable(name="donna.tool.composio_wait_for_connections", run_type="tool")
async def composio_wait_for_connections(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot wait: no user_id in scope.")
    raw = args.get("toolkits") or []
    toolkits = [str(t).strip() for t in raw if str(t).strip()]
    if not toolkits:
        return text_content("Cannot wait: 'toolkits' is required.")
    mode = args.get("mode") or "all"
    timeout = int(args.get("timeout_seconds") or 120)

    res = await composio_meta.wait_for_connections(
        user_id=user_id, toolkits=toolkits, mode=mode, timeout_seconds=timeout
    )
    lines = [str(res.get("message") or "")]
    for slug, payload in (res.get("results") or {}).items():
        status = (payload or {}).get("status", "?")
        ca = (payload or {}).get("connected_account_id", "")
        lines.append(f"{slug}: {status} {ca}".rstrip())
    return text_content("\n".join(line for line in lines if line))


@tool(
    "composio_execute_tool",
    "Generic Composio tool invocation. Use for SaaS actions that lack a "
    "typed Donna wrapper. Get the right tool_slug from composio_search_tools "
    "first. Do NOT use for gmail/calendar reads — list_gmail_recent, "
    "read_gmail_thread, list_calendar are faster and structured.",
    {
        "type": "object",
        "properties": {
            "tool_slug": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["tool_slug", "arguments"],
    },
)
@traceable(name="donna.tool.composio_execute_tool", run_type="tool")
async def composio_execute_tool(args):
    from backend.integrations import composio_meta

    user_id = _current_user_id()
    if not user_id:
        return text_content("Cannot execute: no user_id in scope.")
    slug = str(args.get("tool_slug") or "").strip()
    if not slug:
        return text_content("Cannot execute: 'tool_slug' is required.")
    raw_args = args.get("arguments") or {}
    if not isinstance(raw_args, dict):
        return text_content("Cannot execute: 'arguments' must be an object.")

    res = await composio_meta.execute_tool(
        user_id=user_id, tool_slug=slug, arguments=raw_args
    )
    import json as _json
    return text_content(_json.dumps(res, indent=2)[:4000])
```

- [ ] **Step 4: Add the four functions to `DONNA_TOOLS` in `donna_runtime/tools.py`**

Find the existing tuple (currently 14 entries) and append the four new names:

```python
DONNA_TOOLS = (
    recall,
    remember,
    watch,
    schedule,
    check_calendar,
    image,
    web_search,
    agentic_web_search,
    research,
    send_burst,
    connect_integration,
    list_gmail_recent,
    read_gmail_thread,
    list_calendar,
    composio_search_tools,
    composio_manage_connections,
    composio_wait_for_connections,
    composio_execute_tool,
)
```

- [ ] **Step 5: Add the four slugs to `ALLOWED_TOOLS` in `donna_runtime/config.py`**

```python
ALLOWED_TOOLS = (
    "mcp__donna__recall",
    "mcp__donna__remember",
    "mcp__donna__watch",
    "mcp__donna__schedule",
    "mcp__donna__check_calendar",
    "mcp__donna__image",
    "mcp__donna__web_search",
    "mcp__donna__agentic_web_search",
    "mcp__donna__research",
    "mcp__donna__send_burst",
    "mcp__donna__connect_integration",
    "mcp__donna__list_gmail_recent",
    "mcp__donna__read_gmail_thread",
    "mcp__donna__list_calendar",
    "mcp__donna__composio_search_tools",
    "mcp__donna__composio_manage_connections",
    "mcp__donna__composio_wait_for_connections",
    "mcp__donna__composio_execute_tool",
)
```

- [ ] **Step 6: Run — expect 4/4 pass**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_composio_tools_wrapper.py -v
```

- [ ] **Step 7: Commit**

```bash
git add donna_runtime/tools.py donna_runtime/config.py \
        backend/tests/integrations/test_composio_tools_wrapper.py
git commit -m "feat(runtime): expose composio meta-tools to brain"
```

---

### Task 4: Refactor `connect_integration` to delegate to `composio_meta.manage_connections`

**Files:**
- Modify: `backend/memory/tools/connect_integration.py`
- Modify: `backend/tests/integrations/test_connect_integration_tool.py`

- [ ] **Step 1: Update the existing test to monkey-patch the new internal call**

Open `backend/tests/integrations/test_connect_integration_tool.py` and replace the existing `_FakeClient` / monkey-patch pattern with one that stubs `composio_meta.manage_connections`. Keep the assertion shape (status + url + message + pending row) so the contract doesn't change.

```python
# backend/tests/integrations/test_connect_integration_tool.py
from __future__ import annotations

import pytest

from backend.integrations import state
from backend.memory.tools.connect_integration import connect_integration


@pytest.fixture
def stub_manage(monkeypatch):
    captured: dict = {}

    async def _fake(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "results": {
                "gmail": {
                    "status": "INITIATED",
                    "redirect_url": "https://backend.composio.dev/g",
                    "connected_account_id": "ca_g",
                },
                "googlecalendar": {
                    "status": "INITIATED",
                    "redirect_url": "https://backend.composio.dev/c",
                    "connected_account_id": "ca_c",
                },
            },
        }

    monkeypatch.setattr(
        "backend.integrations.composio_meta.manage_connections", _fake
    )
    return captured


@pytest.mark.asyncio
async def test_connect_integration_returns_urls_and_marks_pending(
    db, stub_manage
):
    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail", "calendar"]
    )

    assert res["status"] == "url_sent"
    assert "https://backend.composio.dev/g" in res["message"]
    assert "https://backend.composio.dev/c" in res["message"]
    assert res["urls"] == {
        "gmail": "https://backend.composio.dev/g",
        "calendar": "https://backend.composio.dev/c",
    }
    assert stub_manage["kwargs"]["toolkits"] == ["gmail", "googlecalendar"]

    gmail_row = await state.get_integration_status("u1", "google", "gmail")
    cal_row = await state.get_integration_status("u1", "google", "calendar")
    assert gmail_row.status == "pending"
    assert cal_row.status == "pending"


@pytest.mark.asyncio
async def test_connect_integration_already_connected_short_circuits(
    db, stub_manage, monkeypatch
):
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="ca_existing"
    )

    res = await connect_integration(
        user_id="u1", provider="google", products=["gmail"]
    )

    assert res["status"] == "already_connected"
    assert "kwargs" not in stub_manage  # never called Composio
```

- [ ] **Step 2: Run — expect failure (old impl uses ComposioClient.get_or_create_connection)**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_connect_integration_tool.py -v
```

- [ ] **Step 3: Replace `connect_integration.py` body**

```python
# backend/memory/tools/connect_integration.py
"""connect_integration — get OAuth URL(s) for an external provider.

Delegates to Composio's COMPOSIO_MANAGE_CONNECTIONS meta-tool which handles
auth-config selection and per-toolkit OAuth init in one call. We keep our
own pending/connected mirror in the integrations table so the
[INTEGRATIONS] context block stays informative without polling Composio.
"""
from __future__ import annotations

from typing import Any

from backend.integrations import composio_meta, state
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Generate connect link(s) for an external provider (currently: google, "
    "covering calendar and gmail). Use when:\n"
    "  - the [INTEGRATIONS] context block shows the integration as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a provider\n"
    "Do NOT use when:\n"
    "  - the integration is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a one-line consent message containing one URL per requested "
    "product. Forward verbatim. The user must tap each link."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string", "enum": ["google"]},
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["calendar", "gmail"]},
            "minItems": 1,
        },
    },
    "required": ["provider", "products"],
}

_PRODUCT_TO_TOOLKIT = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
}
_TOOLKIT_TO_PRODUCT = {v: k for k, v in _PRODUCT_TO_TOOLKIT.items()}
_PRODUCT_LABEL = {"gmail": "gmail", "calendar": "calendar"}


def _consent_message(product_links: list[tuple[str, str]]) -> str:
    if len(product_links) == 1:
        product, url = product_links[0]
        return (
            f"need {_PRODUCT_LABEL[product]} to be useful. one-time read "
            f"so i learn who matters to you. tap: {url}"
        )
    products = " + ".join(_PRODUCT_LABEL[p] for p, _ in product_links)
    lines = [
        f"need {products} to be useful. one tap per service "
        f"(google requires a separate consent for each). then we're set:"
    ]
    for product, url in product_links:
        lines.append(f"  {_PRODUCT_LABEL[product]}: {url}")
    return "\n".join(lines)


@instrument_memory_op("integrations.connect")
async def connect_integration(
    user_id: str, provider: str, products: list[str]
) -> dict[str, Any]:
    if provider != "google":
        return {
            "status": "error",
            "url": None,
            "message": f"provider {provider!r} not supported yet",
        }

    existing = []
    for product in products:
        row = await state.get_integration_status(user_id, provider, product)
        existing.append((product, row.status if row else "absent"))

    if all(s == "connected" for _, s in existing):
        return {
            "status": "already_connected",
            "url": None,
            "message": "already connected",
        }

    pending_products = [p for p, s in existing if s != "connected"]
    toolkits = [_PRODUCT_TO_TOOLKIT[p] for p in pending_products]

    res = await composio_meta.manage_connections(
        user_id=user_id, toolkits=toolkits
    )

    product_links: list[tuple[str, str]] = []
    connection_ids: dict[str, str] = {}
    for toolkit, payload in (res.get("results") or {}).items():
        product = _TOOLKIT_TO_PRODUCT.get(toolkit)
        if not product:
            continue
        url = (payload or {}).get("redirect_url")
        ca_id = (payload or {}).get("connected_account_id")
        if url:
            product_links.append((product, url))
        if ca_id:
            connection_ids[product] = ca_id

    for product in products:
        await state.upsert_pending(user_id, provider, product)

    if not product_links:
        return {
            "status": "error",
            "url": None,
            "message": "composio returned no redirect urls",
        }

    return {
        "status": "url_sent",
        "url": product_links[0][1],
        "urls": {p: u for p, u in product_links},
        "message": _consent_message(product_links),
        "connection_ids": connection_ids,
        "connection_id": next(iter(connection_ids.values()), None),
    }
```

- [ ] **Step 4: Run — expect 2/2 pass on connect_integration tests**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/test_connect_integration_tool.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/memory/tools/connect_integration.py \
        backend/tests/integrations/test_connect_integration_tool.py
git commit -m "refactor(integrations): connect_integration delegates to composio meta"
```

---

### Task 5: Teach Donna the connect→wait pattern in the system prompt

**Files:**
- Modify: `donna_runtime/prompt.py`

- [ ] **Step 1: Locate the current `# INTEGRATIONS` section**

```bash
grep -n "^# INTEGRATIONS$" donna_runtime/prompt.py
```

Expected: one line number (the section we added previously).

- [ ] **Step 2: Replace the section body**

Open `donna_runtime/prompt.py` and replace the entire `# INTEGRATIONS` section (between `# INTEGRATIONS` and the next `# `) with:

```
# INTEGRATIONS

External providers live behind composio. The wrapped user prompt may include an [INTEGRATIONS] block showing per-product connection state for google (connected, pending, not_connected, revoked).

For google, prefer connect_integration — it returns a one-message consent line containing one URL per requested product. Forward verbatim. Do not invent a url, do not summarize the consent line, do not strip it.

For anything else (slack, notion, linear, github, etc.), use the composio meta-tools:
  - composio_search_tools(use_case) when you do not recognize the right tool slug
  - composio_manage_connections(toolkits=[...]) to start oauth — returns a redirect url per toolkit
  - composio_wait_for_connections(toolkits=[...], mode="all"|"any") on a follow-up turn to confirm the user finished oauth before you execute anything that depends on it
  - composio_execute_tool(tool_slug, arguments) for the actual call

The connect-then-act flow is two turns: first turn sends the urls and ends. Next turn (when the user pings back) calls wait_for_connections to confirm, then executes. Do not call wait_for_connections in the same turn you send the urls — the user has not tapped them yet.

Once google is connected, use the typed tools first: list_gmail_recent and read_gmail_thread for mail, list_calendar for events. They are faster and structured. Reach for composio_execute_tool only for actions the typed tools do not cover. The user's BIOGRAPHY block in the system prompt already carries a synthesized read of who they are from their mail.

If [INTEGRATIONS] shows pending, a link is already in flight. Do not nag, do not re-issue the link. If revoked, offer to reconnect.
```

- [ ] **Step 3: Verify the prompt builds**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -c "
from donna_runtime.prompt import _DONNA_CORE
assert 'composio_manage_connections' in _DONNA_CORE
assert 'composio_wait_for_connections' in _DONNA_CORE
assert 'composio_search_tools' in _DONNA_CORE
assert 'composio_execute_tool' in _DONNA_CORE
print('prompt sections wired')
"
```

- [ ] **Step 4: Commit**

```bash
git add donna_runtime/prompt.py
git commit -m "feat(prompt): teach donna the composio connect-then-wait pattern"
```

---

### Task 6: Full-suite regression check + live smoke test

- [ ] **Step 1: Run the integration suite — must stay green**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/integrations/ -v
```

Expected: all pass. The connect_integration tests now exercise the new delegate, the meta-tool tests are new, the existing webhook + bootstrap tests are untouched.

- [ ] **Step 2: Run the broader suites**

```bash
PYTHONPATH=. /opt/miniconda3/bin/python -m pytest backend/tests/ tests/ 2>&1 | tail -10
```

Expected: same baseline as before this plan started (one pre-existing failure in `tests/test_image_tool_step1.py`, everything else green).

- [ ] **Step 3: Restart the API server**

Kill any running uvicorn, then:

```bash
/opt/miniconda3/bin/python -m uvicorn api.main:app --port 8080 --log-level info
```

- [ ] **Step 4: Live smoke via WhatsApp Donna**

Send these to WhatsApp Donna in order. Expected behavior in **bold**.

1. `connect google` → **two URLs in one message** (gmail + calendar via the new composio_meta path)
2. Tap both URLs, complete OAuth in the browser
3. `done` → **donna calls composio_wait_for_connections, returns ACTIVE for both, confirms in chat**
4. From a different terminal:
   ```bash
   PYTHONPATH=. /opt/miniconda3/bin/python scripts/reconcile_integrations.py --user-id 986cbc94-ef35-4eb4-9d1f-7efbc76949e9
   ```
   **Expected**: both gmail and calendar flip to connected in the local DB.
5. `whats on my calendar today` → **donna calls list_calendar (typed tool), answers**
6. `bootstrap my email biography`  + run `scripts/smoke_p3.py --user-id 986cbc94-ef35-4eb4-9d1f-7efbc76949e9 --bootstrap-only` → **biography populates, BIOGRAPHY block appears in next turn**

- [ ] **Step 5: Confirm cost dropped**

```bash
tail -50 .donna/events.jsonl | grep '"event": "turn.end"' | tail -3 | python -c "
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    print(f'turn cost=\${e[\"total_cost_usd\"]:.4f} tools={e[\"tools\"]} cache_read={e[\"cache_read_input_tokens\"]}')
"
```

Expected: per-turn `cache_read_input_tokens` should now be in the low thousands (after the `tools=""` + `disable-slash-commands` flags from the prior session) AND the connect/wait turns succeed instead of the prior `connect_integration·fail`.

- [ ] **Step 6: Commit any test fixtures or scripts touched during the live smoke**

If smoke-time changes were needed (e.g. fixing a typo in the prompt or a tool description), commit them now with a single `chore(integrations): smoke fixes` commit.

---

## Risks + Mitigations

- **Risk:** Composio's `COMPOSIO_WAIT_FOR_CONNECTIONS` may block longer than the agent SDK's per-tool timeout. **Mitigation:** wrapper defaults to 120s; if the SDK enforces a shorter cap we lower this in Task 3 step 3 and rely on Donna re-calling on the next turn.
- **Risk:** Composio's response shapes evolve and our `_data()` extraction breaks. **Mitigation:** Task 1's spike captures the actual current shape; tests use that exact shape; if the API shifts the failure surfaces in the meta-tool tests with a clear diff.
- **Risk:** Donna calls `composio_wait_for_connections` in the same turn as `composio_manage_connections` (against prompt instruction), blocking 120s on URLs the user hasn't tapped. **Mitigation:** prompt explicitly forbids this; if she does it anyway in smoke we tighten the wording or split into two distinct tools that share state.

---

## Out of Scope (followups, not this plan)

- Replacing the typed Gmail/Calendar tools with `composio_execute_tool` calls. Typed tools are faster, structured, and used by the bootstrap pipeline — keep them.
- Auto-marking `integrations.status = connected` on a successful `composio_wait_for_connections`. Worth doing but adds a second source of truth (Composio + our DB); decide after live smoke if it's worth it or if reconcile-on-demand is enough.
- Building a generic `tool_use_log` for Composio meta-tool calls (observability). The existing `instrument_memory_op` traces tool entry/exit; richer telemetry can wait.
