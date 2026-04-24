from __future__ import annotations

import inspect

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server

from .config import DonnaAgentConfig, MCP_SERVER_NAME, MCP_SERVER_VERSION, TOOL_NAMESPACE
from .fake_tools import FAKE_ALLOWED_TOOLS, FAKE_DONNA_TOOLS
from .hooks import post_tool_hook, pre_tool_hook
from .prompt import build_system_prompt
from .tools import DONNA_TOOLS


def _tools_for_mode(mode: str):
    if mode == "fake":
        return list(FAKE_DONNA_TOOLS)
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
        tools=_tools_for_mode(cfg.tool_mode),
    )


def build_options(config: DonnaAgentConfig | None = None) -> ClaudeAgentOptions:
    config = config or DonnaAgentConfig()
    # Keep system_prompt stable across turns so the SDK's prefix cache stays
    # warm. Per-turn volatile context is prepended to the user message by the
    # runner via wrap_user_message_with_context().
    kwargs = {
        "model": config.model,
        "system_prompt": build_system_prompt(
            tool_mode=config.tool_mode,
            user_model_block=config.user_model_block,
        ),
        "mcp_servers": {TOOL_NAMESPACE: build_mcp_server(config)},
        "extra_args": {
            "thinking": "enabled" if config.thinking_enabled else "disabled",
            "bare": None,
            "strict-mcp-config": None,
        },
        "allowed_tools": _allowed_for_mode(config.tool_mode, config),
        "disallowed_tools": list(config.disallowed_tools),
        "setting_sources": [],
        "hooks": {
            "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
        },
        "max_turns": config.max_turns,
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
