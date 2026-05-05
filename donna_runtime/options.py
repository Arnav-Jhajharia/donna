from __future__ import annotations

import inspect

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server

from .config import DonnaAgentConfig, MCP_SERVER_NAME, MCP_SERVER_VERSION, TOOL_NAMESPACE
from .fake_tools import FAKE_ALLOWED_TOOLS, FAKE_DONNA_TOOLS
from .hooks import post_tool_hook, pre_tool_hook
from .prompt import build_system_prompt
from .tools import DONNA_TOOLS


def _tools_for_mode(mode: str, *, runtime_mode: str | None = None):
    """Pick the tool palette.

    ``mode`` is the legacy ``tool_mode`` (fake vs real). ``runtime_mode``
    is the new ``DonnaAgentConfig.mode`` (reactive / proactive /
    proactive_tier3). Tier 3 mode gets the FULL reactive palette plus
    Tier-3-specific terminators (skip / kill_attention / reshape_attention)
    and lookup tools (quick_check / read_external). The Tier 3 ``send_burst``
    wrapper REPLACES the reactive one because it carries the push +
    surface_at quadrant args.
    """
    if mode == "fake":
        return list(FAKE_DONNA_TOOLS)
    if runtime_mode == "proactive_tier3":
        from donna_runtime.tools_tier3_sdk import TIER3_SDK_TOOLS

        tier3_only = {t.name for t in TIER3_SDK_TOOLS}
        # Drop reactive tools that conflict with Tier 3 specialized ones
        # (today only ``send_burst`` overlaps; the others are Tier-3-only).
        reactive_kept = [t for t in DONNA_TOOLS if t.name not in tier3_only]
        return reactive_kept + list(TIER3_SDK_TOOLS)
    return list(DONNA_TOOLS)


def _allowed_for_mode(mode: str, config: DonnaAgentConfig):
    if mode == "fake":
        return list(FAKE_ALLOWED_TOOLS)
    return list(config.allowed_tools)


def build_mcp_server(config: DonnaAgentConfig | None = None):
    cfg = config or DonnaAgentConfig()
    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        tools=_tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode),
    )


def build_options(config: DonnaAgentConfig | None = None) -> ClaudeAgentOptions:
    config = config or DonnaAgentConfig()
    # Keep system_prompt stable across turns so the SDK's prefix cache stays
    # warm. Per-turn volatile context is prepended to the user message by the
    # runner via wrap_user_message_with_context().
    env: dict[str, str] = {}
    if config.cache_ttl_1h:
        # Forwarded to the spawned `claude` CLI subprocess; the CLI converts it
        # into the 1h cache-TTL beta header on /v1/messages.
        env["ENABLE_PROMPT_CACHING_1H"] = "1"

    # Phase 2A: Tier 3 mode picks its own system prompt + max_turns.
    if config.mode == "proactive_tier3":
        from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT
        system_prompt = TIER3_SYSTEM_PROMPT
        max_turns = config.tier3_max_turns
    else:
        system_prompt = build_system_prompt(tool_mode=config.tool_mode)
        max_turns = config.max_turns

    kwargs = {
        "model": config.model,
        "system_prompt": system_prompt,
        "mcp_servers": {TOOL_NAMESPACE: build_mcp_server(config)},
        "extra_args": {
            "thinking": "enabled" if config.thinking_enabled else "disabled",
            "bare": None,
            "strict-mcp-config": None,
            # Empty string disables ALL built-in tools (Bash/Read/Write/Edit/etc).
            # Donna only uses MCP tools — built-in schemas are pure overhead.
            "tools": "",
            # Skip skill descriptions; --bare alone still resolves /skill-name.
            "disable-slash-commands": None,
            # Keep dynamic per-machine sections out of the system prompt so the
            # prefix cache stays warm across machines and turns.
            "exclude-dynamic-system-prompt-sections": None,
        },
        "env": env,
        "allowed_tools": _allowed_for_mode(config.tool_mode, config),
        "disallowed_tools": list(config.disallowed_tools),
        "setting_sources": [],
        "hooks": {
            "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
        },
        "max_turns": max_turns,
        "resume": config.resume_session_id,
        "fork_session": config.fork_session,
        "skills": [],
        "tools": [],
    }
    return ClaudeAgentOptions(**_filter_supported_options(kwargs))


def _filter_supported_options(kwargs: dict[str, object]) -> dict[str, object]:
    signature = inspect.signature(ClaudeAgentOptions)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return {key: value for key, value in kwargs.items() if value is not None}
    return {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters and value is not None
    }
