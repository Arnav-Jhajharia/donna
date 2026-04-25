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


_DEFAULT_FINAL_CALLBACK = "https://platform.composio.dev/dashboard"


async def initiate_oauth_chain(
    *,
    user_id: str,
    toolkit_to_auth_config: dict[str, str],
    final_callback_url: str = _DEFAULT_FINAL_CALLBACK,
) -> dict:
    """Build a redirect chain so the user only taps ONE URL.

    Each toolkit's ``callback_url`` points to the next toolkit's
    ``redirect_url`` so the browser walks the chain after a single
    OAuth approval. The very last toolkit in the chain falls through
    to ``final_callback_url`` (default: Composio dashboard).

    Returns ``{"first_url", "chain": [{toolkit, auth_config_id,
    redirect_url, connected_account_id}]}`` where ``chain`` is in the
    same order as ``toolkit_to_auth_config``.
    """
    composio = _composio()
    items = list(toolkit_to_auth_config.items())  # ordered

    # Build in REVERSE so each callback points to the next URL.
    chain_url = final_callback_url
    reversed_chain: list[dict] = []
    for toolkit, ac_id in reversed(items):
        req = composio.connected_accounts.initiate(
            user_id=user_id,
            auth_config_id=ac_id,
            callback_url=chain_url,
        )
        chain_url = req.redirect_url
        reversed_chain.append(
            {
                "toolkit": toolkit,
                "auth_config_id": ac_id,
                "redirect_url": req.redirect_url,
                "connected_account_id": req.id,
            }
        )

    chain_in_order = list(reversed(reversed_chain))
    return {
        "first_url": chain_in_order[0]["redirect_url"],
        "chain": chain_in_order,
    }


async def resolve_auth_configs(
    *, toolkits: list[str], user_id: str
) -> dict[str, str]:
    """Map toolkit slug -> auth_config_id.

    Looks up an existing auth config per toolkit via
    ``composio.auth_configs.list()`` (most-recent wins for duplicates).
    For toolkits with no existing auth config, falls back to
    ``manage_connections`` to auto-create one (managed toolkits like
    googledrive provision on first request) and reads the
    ``auth_config_id`` from the response.

    Returns a dict in the same order as ``toolkits``; toolkits that
    cannot be resolved are omitted.
    """
    composio = _composio()
    listing = composio.auth_configs.list()
    items = listing.items if hasattr(listing, "items") else list(listing)

    # last-write-wins -> most recently registered config per toolkit
    by_toolkit: dict[str, str] = {}
    for ac in items:
        slug = getattr(getattr(ac, "toolkit", None), "slug", None)
        if slug:
            by_toolkit[slug] = ac.id

    out: dict[str, str] = {}
    missing: list[str] = []
    for tk in toolkits:
        if tk in by_toolkit:
            out[tk] = by_toolkit[tk]
        else:
            missing.append(tk)

    if missing:
        res = await manage_connections(user_id=user_id, toolkits=missing)
        for tk in missing:
            payload = (res.get("results") or {}).get(tk) or {}
            ac_id = payload.get("auth_config_id")
            if ac_id:
                out[tk] = ac_id

    # Preserve original toolkit order
    return {tk: out[tk] for tk in toolkits if tk in out}
