"""Gold-spec tests: each example validates, no duplicates, ambient-signal only."""
from __future__ import annotations

import pytest

from donna.attention.examples.gold_specs import GOLD_EXAMPLES
from donna.attention.schema import AttentionSpec
from donna.attention.vocabulary import SourceType


# Banned source types — user-organized workspaces.
_BANNED_TOKENS = {"notion", "linear", "airtable", "trello", "asana", "clickup"}


@pytest.mark.unit
def test_gold_examples_count_at_least_15():
    assert len(GOLD_EXAMPLES) >= 15


@pytest.mark.unit
def test_gold_example_ids_unique():
    ids = [e.example_id for e in GOLD_EXAMPLES]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
@pytest.mark.parametrize("example", GOLD_EXAMPLES, ids=[e.example_id for e in GOLD_EXAMPLES])
def test_gold_example_spec_validates(example):
    # Round trip must preserve equality.
    payload = example.spec.model_dump(mode="json")
    rebuilt = AttentionSpec.model_validate(payload)
    assert rebuilt == example.spec


@pytest.mark.unit
@pytest.mark.parametrize("example", GOLD_EXAMPLES, ids=[e.example_id for e in GOLD_EXAMPLES])
def test_gold_example_uses_only_ambient_sources(example):
    for src in example.spec.sources:
        value = src.type.value.lower()
        for banned in _BANNED_TOKENS:
            assert banned not in value, f"{example.example_id} uses banned source {value}"
        assert isinstance(src.type, SourceType)


@pytest.mark.unit
@pytest.mark.parametrize("example", GOLD_EXAMPLES, ids=[e.example_id for e in GOLD_EXAMPLES])
def test_gold_example_has_paraphrases_and_rationale(example):
    assert len(example.intent_examples) >= 3, example.example_id
    assert example.rationale, example.example_id
