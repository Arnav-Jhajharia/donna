"""Thin async wrappers around Composio's meta-tools.

Composio's COMPOSIO_* meta-tools handle the agent-side of integrations:
discovery (search), connection lifecycle (manage + wait), and generic
execute. We expose them as Donna tools so any toolkit composio supports
becomes connectable without per-provider code.

The Composio Python SDK is sync — we wrap each call in a coroutine for
the agent runtime, but no thread offload is needed (the calls are short
HTTP round-trips except WAIT_FOR_CONNECTIONS, which the SDK polls
internally and we should NOT block the event loop on).

Note: every COMPOSIO_* meta-tool call must pass
``dangerously_skip_version_check=True`` to ``composio.tools.execute`` —
otherwise the SDK raises ``ToolVersionRequiredError``. The flag is safe
for these meta-tools because they are versionless.
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
    """Composio wraps everything in ``{data: {...}, error, successful}``.
    We only ever care about ``data`` — return it (or empty dict on missing).
    """
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
        dangerously_skip_version_check=True,
    ))


async def manage_connections(*, user_id: str, toolkits: list[str]) -> dict:
    """COMPOSIO_MANAGE_CONNECTIONS — initiate OAuth for missing toolkits.

    Returns dict with ``results.<toolkit>.{status, redirect_url, auth_config_id}``.
    Status is lowercase (``"initiated"``). The ``connected_account_id`` is
    NOT present in this response — it appears only after WAIT_FOR_CONNECTIONS
    returns ``"active"``. Idempotent at Composio: already-active toolkits
    are skipped.
    """
    composio = _composio()
    return _data(composio.tools.execute(
        "COMPOSIO_MANAGE_CONNECTIONS",
        user_id=user_id,
        arguments={"toolkits": list(toolkits)},
        dangerously_skip_version_check=True,
    ))


async def wait_for_connections(
    *,
    user_id: str,
    toolkits: list[str],
    mode: Literal["all", "any"] = "all",
    timeout_seconds: int = 120,
) -> dict:
    """COMPOSIO_WAIT_FOR_CONNECTIONS — block until OAuth completes.

    ``mode="all"`` waits for every toolkit; ``mode="any"`` returns once
    one is active. The SDK polls Composio internally; the call returns
    when the condition is met or the timeout expires. Status in the
    response is lowercase (``"active"``); the ``connected_account_id``
    field is populated once the toolkit is active.
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
        dangerously_skip_version_check=True,
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
        dangerously_skip_version_check=True,
    ))
