"""Subject-safety tests for extract_user_facts.

Regression coverage for the "Aayam Bansal" class of bug: Haiku extracts a
third party's name/profession from a user message and writes it to the
user's own facts row.
"""
from __future__ import annotations

import pytest

from backend.memory.hooks import extract_user_facts
from backend.memory.hooks.extract_user_facts import (
    _message_is_first_person_about_self,
)
from backend.memory.user_facts.schema import FactKey


# ─── pure filter tests ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "i'm a nurse",
        "I live in Tokyo",
        "call me sam",
        "I've been a founder for 3 years",
        "my job is heavy lifting",  # "my" alone is first-person
        "i moved to berlin last month",
    ],
)
def test_first_person_self_statements_accepted(message: str) -> None:
    assert _message_is_first_person_about_self(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "my friend Aayam Bansal is in Synthetic Sciences",
        "Sarah just moved to New York",
        "my manager's name is Priya",
        "I just met a founder from Lagos",
        "her profession is interior design",
        "he is a surgeon in seoul",
        "my cofounder runs product",
        "my boyfriend works at stripe",
        "they're in a WhatsApp group",
    ],
)
def test_third_party_statements_rejected(message: str) -> None:
    assert _message_is_first_person_about_self(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "yes",
        "ok",
        "thanks",
        "tokyo",
    ],
)
def test_ambiguous_no_first_person_rejected(message: str) -> None:
    assert _message_is_first_person_about_self(message) is False


# ─── integration: suppression + allowance ────────────────────────────────


class _FakeBatch:
    def __init__(self, items: list[dict]) -> None:
        self.extracted = [_FakeItem(**i) for i in items]


class _FakeItem:
    def __init__(
        self,
        key: str,
        value: str,
        confidence: str = "high",
        is_correction: bool = False,
    ) -> None:
        self.key = key
        self.value = value
        self.confidence = confidence
        self.is_correction = is_correction


@pytest.mark.asyncio
async def test_third_party_identity_extraction_is_suppressed(monkeypatch):
    """Haiku returns a third-party name; the filter must block the write."""
    writes: list[dict] = []

    async def _fake_call_structured(**kwargs):
        return _FakeBatch(
            [
                {"key": FactKey.PREFERRED_NAME.value, "value": "Aayam Bansal", "confidence": "high"},
                {"key": FactKey.PROFESSION.value, "value": "Synthetic Sciences", "confidence": "high"},
            ]
        )

    async def _fake_update_user_fact(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(extract_user_facts, "call_structured", _fake_call_structured)
    monkeypatch.setattr(extract_user_facts, "update_user_fact", _fake_update_user_fact)

    await extract_user_facts.run(
        {
            "user_id": "u-arnav",
            "inbound": "my friend Aayam Bansal is in Synthetic Sciences",
            "user_facts": {},
        }
    )

    # Only the offline language detection may have fired (primary_language);
    # no identity-shaped fields should have been written.
    identity_keys = {
        FactKey.PREFERRED_NAME.value,
        FactKey.PROFESSION.value,
        FactKey.HOME_CITY.value,
        FactKey.CURRENT_CITY.value,
        FactKey.AGE_GROUP.value,
        FactKey.LIFE_STAGE.value,
        FactKey.HOUSEHOLD.value,
    }
    written_identity_keys = {w["key"] for w in writes if w.get("key") in identity_keys}
    assert written_identity_keys == set(), (
        f"third-party extraction leaked into user facts: {writes}"
    )


@pytest.mark.asyncio
async def test_first_person_identity_extraction_is_allowed(monkeypatch):
    """Legitimate first-person self-statements must still land."""
    writes: list[dict] = []

    async def _fake_call_structured(**kwargs):
        return _FakeBatch(
            [
                {"key": FactKey.PROFESSION.value, "value": "nurse", "confidence": "high"},
            ]
        )

    async def _fake_update_user_fact(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(extract_user_facts, "call_structured", _fake_call_structured)
    monkeypatch.setattr(extract_user_facts, "update_user_fact", _fake_update_user_fact)

    await extract_user_facts.run(
        {
            "user_id": "u-arnav",
            "inbound": "I'm a nurse at the downtown clinic",
            "user_facts": {},
        }
    )

    profession_writes = [w for w in writes if w["key"] == FactKey.PROFESSION.value]
    assert len(profession_writes) == 1, (
        f"first-person profession self-statement was suppressed: {writes}"
    )
    assert profession_writes[0]["value"] == "nurse"
