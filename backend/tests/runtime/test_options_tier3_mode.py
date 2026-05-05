"""build_options mode-aware tool registration for Tier 3."""
from __future__ import annotations

import pytest

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.options import _tools_for_mode, build_options


def test_tools_for_mode_returns_full_palette_for_proactive_tier3():
    """When cfg.mode == 'proactive_tier3', the palette is the full reactive
    set PLUS the Tier 3 specialized tools (skip / kill / reshape / quick_check
    / read_external), with Tier 3's send_burst replacing reactive's."""
    from donna_runtime.tools import DONNA_TOOLS
    from donna_runtime.tools_tier3_sdk import TIER3_SDK_TOOLS

    cfg = DonnaAgentConfig(mode="proactive_tier3")
    tools = _tools_for_mode(cfg.tool_mode, runtime_mode=cfg.mode)
    tool_names = {t.name for t in tools}

    # Every Tier 3 specialized tool present.
    for t in TIER3_SDK_TOOLS:
        assert t.name in tool_names, f"missing Tier 3 tool: {t.name}"

    # Reactive lookup tools the model needs to form an answer.
    for must_have in ("recall", "list_attentions", "list_reminders", "search_gmail", "gather_context"):
        assert must_have in tool_names, f"missing reactive lookup: {must_have}"

    # Tier 3's send_burst, not reactive's. We don't double-register.
    send_bursts = [t for t in tools if t.name == "send_burst"]
    assert len(send_bursts) == 1, "send_burst should appear exactly once"

    # Total = reactive count (minus 1 for replaced send_burst) + 6 Tier 3 tools.
    assert len(tools) == (len(DONNA_TOOLS) - 1) + len(TIER3_SDK_TOOLS)


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
        tier3_max_turns=5,
    )
    options = build_options(cfg)
    # SDK options expose max_turns; verify it's the tier3 value, not the
    # default 6.
    max_turns = getattr(options, "max_turns", None)
    assert max_turns == 5


def test_tier3_max_turns_default_is_5():
    """The tier3_max_turns default bumped 3 → 5 to allow 1-2 lookups before
    terminating now that Tier 3 has the full reactive tool palette."""
    cfg = DonnaAgentConfig(mode="proactive_tier3")
    assert cfg.tier3_max_turns == 5


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
