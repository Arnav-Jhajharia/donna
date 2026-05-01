"""Structural + behavioral tests for the donna_information tool."""
from __future__ import annotations

import pytest

from backend.memory.tools import donna_information as mod


def test_module_surface():
    assert isinstance(mod.DESCRIPTION, str) and mod.DESCRIPTION
    assert "Use when" in mod.DESCRIPTION
    assert "Do NOT use" in mod.DESCRIPTION
    assert isinstance(mod.INPUT_SCHEMA, dict)
    assert mod.INPUT_SCHEMA.get("type") == "object"
    assert "topic" in mod.INPUT_SCHEMA["properties"]
    assert callable(mod.donna_information)


def test_donna_info_keys_are_snake_case_strings():
    for key, value in mod.DONNA_INFO.items():
        assert isinstance(key, str) and key
        assert key == key.lower()
        assert " " not in key
        assert isinstance(value, str)


def test_donna_info_is_immutable():
    with pytest.raises(TypeError):
        mod.DONNA_INFO["privacy_policy"] = "leak"  # type: ignore[index]


@pytest.mark.asyncio
async def test_unknown_topic_returns_no_hits():
    result = await mod.donna_information(user_id="u1", topic="nonsense")
    assert result["status"] == "no_hits"
    assert result["payload"]["answer"] is None


@pytest.mark.asyncio
async def test_uncalibrated_topic_returns_no_hits():
    # Every topic ships uncalibrated (empty string). Until the team fills
    # answers in, the tool MUST refuse rather than letting the model invent.
    result = await mod.donna_information(user_id="u1", topic="privacy_policy")
    assert result["status"] == "no_hits"


@pytest.mark.asyncio
async def test_topic_listing_when_omitted():
    result = await mod.donna_information(user_id="u1", topic=None)
    # With no calibrated topics yet, listing is empty but still well-formed.
    assert result["status"] in {"ok", "no_hits"}
    assert "topics" in result["payload"]
    assert isinstance(result["payload"]["topics"], list)


@pytest.mark.asyncio
async def test_calibrated_topic_returns_curated_answer(monkeypatch):
    # Simulate a calibrated answer to verify the happy path.
    monkeypatch.setitem(mod._DONNA_INFO_RAW, "privacy_policy", "your data stays yours.")
    try:
        result = await mod.donna_information(
            user_id="u1", topic="Privacy_Policy"
        )
        assert result["status"] == "ok"
        assert result["payload"]["topic"] == "privacy_policy"
        assert result["payload"]["answer"] == "your data stays yours."

        listing = await mod.donna_information(user_id="u1")
        assert listing["status"] == "ok"
        assert "privacy_policy" in listing["payload"]["topics"]
    finally:
        mod._DONNA_INFO_RAW["privacy_policy"] = ""


@pytest.mark.asyncio
async def test_topic_is_normalized():
    result = await mod.donna_information(user_id="u1", topic="  ")
    # Whitespace-only topic is treated as "list mode".
    assert "topics" in result["payload"]
