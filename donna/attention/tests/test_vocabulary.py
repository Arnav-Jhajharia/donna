"""Vocabulary tests (v2): enum shape + source params coverage."""
from __future__ import annotations

import pytest

from donna.attention.vocabulary import (
    SOURCE_PARAMS_MODELS,
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
    output_schema_for_card,
    vocabulary_summary,
)


@pytest.mark.unit
def test_source_type_count():
    # 29 = original 27 + INTERNAL_OBSERVATIONS + USER_ELICITATION
    # (INTERNAL_ATTENTION was already included, so count is 30 actually).
    assert len(list(SourceType)) == 30


@pytest.mark.unit
def test_every_source_type_has_params_model():
    missing = [s for s in SourceType if s not in SOURCE_PARAMS_MODELS]
    assert missing == []


@pytest.mark.unit
def test_card_catalog_is_six():
    assert {c.value for c in CardType} == {
        "event_stream",
        "tally",
        "brief",
        "prep_doc",
        "open_loop",
        "ping",
    }


@pytest.mark.unit
def test_every_card_has_output_schema():
    for c in CardType:
        schema = output_schema_for_card(c)
        assert schema["type"] == "object"
        assert "properties" in schema


@pytest.mark.unit
def test_enums_are_str_enums():
    for e in (SourceType, CardType, SubjectType, CadenceType, SurfaceLevel, DomainTag):
        for member in e:
            assert isinstance(member.value, str)


@pytest.mark.unit
def test_no_workspace_tools_in_source_types():
    banned = {"notion", "linear", "airtable", "trello", "asana", "clickup"}
    for s in SourceType:
        for word in banned:
            assert word not in s.value.lower(), f"banned workspace tool: {s.value}"


@pytest.mark.unit
def test_vocabulary_summary_shape():
    summary = vocabulary_summary()
    assert set(summary.keys()) == {
        "source_types",
        "card_types",
        "subject_types",
        "cadence_types",
        "surface_levels",
        "domain_tags",
    }
    assert len(summary["card_types"]) == 6
    assert len(summary["subject_types"]) == 5
    assert len(summary["cadence_types"]) == 5


@pytest.mark.unit
def test_enum_values_are_stable():
    assert SurfaceLevel.URGENT.value == "urgent"
    assert CadenceType.ON_EVENT.value == "on_event"
    assert CardType.PING.value == "ping"
    assert SourceType.USER_ELICITATION.value == "user_elicitation"
    assert SourceType.INTERNAL_OBSERVATIONS.value == "internal_observations"
