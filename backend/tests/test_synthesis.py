"""Synthesis structural tests — verify callables exist with the expected shape.

Runtime behavior (DB + Haiku) is exercised in integration tests.
"""
from __future__ import annotations

import asyncio
import inspect

from backend.memory.synthesis import living_profile, procedural_rules_tier2


def test_synthesize_nightly_profile_is_async_callable():
    fn = living_profile.synthesize_nightly_profile
    assert asyncio.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["user_id"]


def test_synthesize_tier2_rules_is_async_callable():
    fn = procedural_rules_tier2.synthesize_tier2_rules
    assert asyncio.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["user_id"]


def test_living_profile_prompt_exists():
    from pathlib import Path

    p = Path(living_profile.__file__).parent / "prompts" / "living_profile.md"
    assert p.exists() and p.read_text().strip()


def test_tier2_prompt_exists():
    from pathlib import Path

    p = Path(procedural_rules_tier2.__file__).parent / "prompts" / "procedural_rules_tier2.md"
    assert p.exists() and p.read_text().strip()
