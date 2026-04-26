"""Tests for the pre-BRAIN deterministic fact detector.

This is the regex-only path that catches explicit identity declarations and
corrections before the USER MODEL block is rendered. No LLM involved.
"""
from __future__ import annotations

import pytest

from backend.memory.hooks import deterministic_fact_detector as detector
from backend.memory.user_facts.schema import FactKey


# ─── pattern detection ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message,expected_key,expected_value,expected_correction",
    [
        # name patterns
        ("my name is arnav", FactKey.PREFERRED_NAME, "arnav", True),
        ("my name is arnav btw not aayam", FactKey.PREFERRED_NAME, "arnav", True),
        ("call me sam", FactKey.PREFERRED_NAME, "sam", True),
        ("actually i'm arnav", FactKey.PREFERRED_NAME, "arnav", True),
        ("actually im arnav not aayam", FactKey.PREFERRED_NAME, "arnav", True),
        # profession patterns
        ("i'm a nurse", FactKey.PROFESSION, "nurse", False),
        ("im a founder", FactKey.PROFESSION, "founder", False),
        ("i work as an engineer", FactKey.PROFESSION, "engineer", False),
        # city patterns
        ("i live in tokyo", FactKey.CURRENT_CITY, "tokyo", False),
        ("i moved to berlin", FactKey.CURRENT_CITY, "berlin", False),
        ("i'm in singapore", FactKey.CURRENT_CITY, "singapore", False),
        ("im in new york city now", FactKey.CURRENT_CITY, "new york city", False),
        ("i'm from london", FactKey.HOME_CITY, "london", False),
    ],
)
def test_detects_canonical_patterns(
    message: str, expected_key: FactKey, expected_value: str, expected_correction: bool
) -> None:
    results = detector.detect_facts(message)
    assert len(results) >= 1, f"no detection for {message!r}"
    match = next((r for r in results if r.key == expected_key), None)
    assert match is not None, f"expected {expected_key.value} not detected in {results!r}"
    assert match.value.lower() == expected_value.lower(), (
        f"expected value {expected_value!r}, got {match.value!r} for {message!r}"
    )
    assert match.is_correction == expected_correction


@pytest.mark.parametrize(
    "message",
    [
        # third-party mentions — must not match
        "my friend arnav is a nurse",
        "her name is sarah",
        "my cofounder lives in berlin",
        "my mom is from london",
        "my manager is a designer",
        # no first-person marker
        "arnav is great",
        "tokyo is nice this time of year",
        # ambiguous / no pattern
        "hey",
        "sure",
        "lol",
        "what do you think",
    ],
)
def test_rejects_third_party_and_unrelated(message: str) -> None:
    assert detector.detect_facts(message) == []


def test_stopwords_truncate_value() -> None:
    """'my name is arnav btw not aayam' extracts 'arnav', not the whole tail."""
    results = detector.detect_facts("my name is arnav btw not aayam")
    assert len(results) == 1
    assert results[0].value.lower() == "arnav"


def test_only_first_matching_key_wins() -> None:
    """If one key has multiple regex hits, only the first fires."""
    results = detector.detect_facts("my name is sam, call me sam")
    names = [r for r in results if r.key == FactKey.PREFERRED_NAME]
    assert len(names) == 1


# ─── integration with update_user_fact ────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_detected_facts_writes_through_update_user_fact(monkeypatch):
    writes: list[dict] = []

    async def _fake_update(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(detector, "update_user_fact", _fake_update)

    detected = detector.detect_facts("my name is arnav btw not aayam")
    assert len(detected) == 1
    await detector.apply_detected_facts("u-test", detected)

    assert len(writes) == 1
    assert writes[0]["key"] == FactKey.PREFERRED_NAME.value
    assert writes[0]["value"] == "arnav"
    # USER_CORRECTION source wins over existing facts in resolve_write.
    assert writes[0]["source"].value == "user_correction"


@pytest.mark.asyncio
async def test_run_is_noop_for_no_matches(monkeypatch):
    writes: list[dict] = []

    async def _fake_update(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(detector, "update_user_fact", _fake_update)

    await detector.run("u-test", "hey what's going on")
    assert writes == []


@pytest.mark.asyncio
async def test_run_is_noop_for_third_party(monkeypatch):
    writes: list[dict] = []

    async def _fake_update(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(detector, "update_user_fact", _fake_update)

    await detector.run("u-test", "my friend arnav lives in tokyo")
    assert writes == [], f"third-party mention leaked into user facts: {writes}"
