"""build_options mode-aware tool registration for Tier 3."""
from __future__ import annotations

import pytest

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.options import _tools_for_mode, build_options


def test_tools_for_mode_returns_tier3_tools_for_proactive_tier3():
    """When cfg.mode == 'proactive_tier3', the tool palette is the Tier 3 set."""
    from donna_runtime.tools_tier3_sdk import TIER3_SDK_TOOLS

    cfg = DonnaAgentConfig(mode="proactive_tier3")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    tool_names = {t.name for t in tools}
    expected_names = {t.name for t in TIER3_SDK_TOOLS}
    assert tool_names == expected_names


def test_tools_for_mode_returns_donna_tools_for_reactive():
    """Default reactive mode still returns the full DONNA_TOOLS palette."""
    from donna_runtime.tools import DONNA_TOOLS

    cfg = DonnaAgentConfig(mode="reactive")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    assert len(tools) == len(DONNA_TOOLS)


def test_tools_for_mode_returns_donna_tools_for_proactive():
    """Legacy proactive mode also gets the reactive tool palette today."""
    from donna_runtime.tools import DONNA_TOOLS

    cfg = DonnaAgentConfig(mode="proactive")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    assert len(tools) == len(DONNA_TOOLS)


def test_tools_for_mode_back_compat_signature_without_runtime_mode():
    """Calling _tools_for_mode without the new runtime_mode kwarg must
    still work (defaults to reactive). Existing call sites unchanged."""
    from donna_runtime.tools import DONNA_TOOLS

    tools = _tools_for_mode("real")
    assert len(tools) == len(DONNA_TOOLS)


def test_build_options_uses_tier3_max_turns_for_tier3_mode():
    cfg = DonnaAgentConfig(
        mode="proactive_tier3",
        tier3_max_turns=3,
    )
    options = build_options(cfg)
    # SDK options expose max_turns; verify it's the tier3 value, not the
    # default 6.
    max_turns = getattr(options, "max_turns", None)
    assert max_turns == 3


def test_build_options_uses_default_max_turns_for_reactive_mode():
    cfg = DonnaAgentConfig(mode="reactive")
    options = build_options(cfg)
    max_turns = getattr(options, "max_turns", None)
    assert max_turns == 6


def test_build_options_uses_tier3_system_prompt_for_tier3_mode():
    from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT

    cfg = DonnaAgentConfig(mode="proactive_tier3")
    options = build_options(cfg)
    system_prompt = str(getattr(options, "system_prompt", "") or "")
    # Tier 3 system prompt is distinctive — has 'editorial mode' on line 1.
    assert "editorial mode" in system_prompt.lower()
    assert system_prompt.strip().startswith(TIER3_SYSTEM_PROMPT.strip()[:50])
