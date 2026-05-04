"""Tier 3 system prompt + DonnaAgentConfig mode wiring."""
from __future__ import annotations

import pytest

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT


def test_tier3_system_prompt_states_editorial_default():
    p = TIER3_SYSTEM_PROMPT.lower()
    assert "editorial" in p
    assert "skip" in p
    assert "default" in p


def test_tier3_system_prompt_lists_terminators():
    p = TIER3_SYSTEM_PROMPT
    for tool in ("send_burst", "skip", "reshape_attention", "kill_attention"):
        assert tool in p


def test_tier3_system_prompt_warns_against_em_dashes():
    """Donna voice charter is preserved even in editorial mode."""
    p = TIER3_SYSTEM_PROMPT.lower()
    assert "em dash" in p or "em-dash" in p


def test_tier3_system_prompt_states_3_turns():
    """Lower max_turns is part of the editorial discipline."""
    assert "3 turn" in TIER3_SYSTEM_PROMPT.lower() or "three turn" in TIER3_SYSTEM_PROMPT.lower()


def test_tier3_system_prompt_lists_read_tools():
    """quick_check and read_external are in the prompt."""
    p = TIER3_SYSTEM_PROMPT
    assert "quick_check" in p
    assert "read_external" in p


def test_donna_agent_config_accepts_tier3_mode():
    cfg = DonnaAgentConfig(mode="proactive_tier3", tier3_max_turns=3)
    assert cfg.mode == "proactive_tier3"
    assert cfg.tier3_max_turns == 3


def test_donna_agent_config_default_tier3_max_turns_is_3():
    cfg = DonnaAgentConfig(mode="proactive_tier3")
    assert cfg.tier3_max_turns == 3


def test_donna_agent_config_existing_modes_still_work():
    """Backwards compat: reactive + proactive must still construct."""
    assert DonnaAgentConfig(mode="reactive").mode == "reactive"
    assert DonnaAgentConfig(mode="proactive").mode == "proactive"
