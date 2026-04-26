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


def test_synthesize_full_profile_is_async_callable():
    fn = living_profile.synthesize_full_profile
    assert asyncio.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["user_id"]
    # Back-compat alias points at the same coroutine.
    assert living_profile.synthesize_nightly_profile is fn


def test_refresh_morning_digest_is_async_callable():
    fn = living_profile.refresh_morning_digest
    assert asyncio.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["user_id"]


def test_full_profile_schema_carries_v2_fields():
    schema = living_profile._FullProfile.model_json_schema()
    properties = schema.get("properties") or {}
    for required in (
        "current_situation",
        "active_tensions",
        "key_people",
        "what_changed_this_week",
        "watch_for_tomorrow",
        "emotional_temperature",
        "rhythm",
        "yesterday",
        "today_shape",
    ):
        assert required in properties, f"missing field {required}"


def test_morning_digest_schema_carries_only_two_fields():
    schema = living_profile._MorningDigest.model_json_schema()
    properties = schema.get("properties") or {}
    assert set(properties).issuperset({"yesterday", "today_shape"})
    # Morning pass intentionally narrow — does not regenerate situation,
    # rhythm, people, etc.
    assert "current_situation" not in properties
    assert "rhythm" not in properties


def test_synthesize_tier2_rules_is_async_callable():
    fn = procedural_rules_tier2.synthesize_tier2_rules
    assert asyncio.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["user_id"]


def test_living_profile_prompt_exists():
    from pathlib import Path

    p = Path(living_profile.__file__).parent / "prompts" / "living_profile.md"
    assert p.exists() and p.read_text().strip()


def test_living_profile_morning_prompt_exists():
    from pathlib import Path

    p = (
        Path(living_profile.__file__).parent
        / "prompts"
        / "living_profile_morning.md"
    )
    assert p.exists() and p.read_text().strip()


def test_tier2_prompt_exists():
    from pathlib import Path

    p = Path(procedural_rules_tier2.__file__).parent / "prompts" / "procedural_rules_tier2.md"
    assert p.exists() and p.read_text().strip()
