"""Schema tests (v2): card catalog, subject, resolve_if, shadow, Ping degenerate shape."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionSpec,
    AttentionStatus,
    Cadence,
    Dedup,
    Extractor,
    ShadowState,
    Source,
    Subject,
    SurfaceEscalation,
    SurfacePolicy,
)
from donna.attention.vocabulary import (
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
)


def _valid_spec() -> AttentionSpec:
    return AttentionSpec(
        title="Poke watch",
        description="Ongoing ambient monitoring of Poke for material updates.",
        card=CardType.EVENT_STREAM,
        subject=Subject(name="Poke", type=SubjectType.ENTITY),
        domain_tags=[DomainTag.COMPETITIVE_INTEL, DomainTag.WORK],
        sources=[
            Source(
                type=SourceType.WEB_EXA,
                params={"query": "Poke AI startup", "num_results": 10},
            ),
            Source(
                type=SourceType.WEB_GOOGLE_NEWS,
                params={"query": "Poke AI", "language": "en", "country": "US"},
            ),
        ],
        extractor=Extractor(
            prompt="Extract material product, funding, or leadership events about Poke.",
        ),
        cadence=Cadence(type=CadenceType.SCHEDULED, params={"cron": "0 9 * * *"}),
        surface_policy=SurfacePolicy(
            default=SurfaceLevel.DIGEST,
            urgent_if="event_type in ['funding','major_launch']",
            resolve_if=None,
        ),
        relevance_threshold=0.6,
    )


def _valid_ping() -> AttentionSpec:
    return AttentionSpec(
        title="Call mom",
        description="Ping the user at 6pm to call mom.",
        card=CardType.PING,
        subject=Subject(name="call mom", type=SubjectType.EVENT),
        domain_tags=[DomainTag.SOCIAL, DomainTag.REMINDER],
        sources=[
            Source(
                type=SourceType.USER_ELICITATION,
                params={"question": "Call mom?", "expected_shape": "confirmation"},
            )
        ],
        extractor=Extractor(prompt="Fire the ping message at trigger time."),
        cadence=Cadence(
            type=CadenceType.ONE_SHOT, params={"trigger_at": "2026-05-01T18:00:00Z"}
        ),
        surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
    )


@pytest.mark.unit
def test_valid_spec_roundtrip():
    spec = _valid_spec()
    payload = spec.model_dump(mode="json")
    rebuilt = AttentionSpec.model_validate(payload)
    assert rebuilt == spec


@pytest.mark.unit
def test_output_schema_derived_from_card():
    spec = _valid_spec()
    assert spec.output_schema["type"] == "object"
    assert "events" in spec.output_schema["properties"]


@pytest.mark.unit
def test_ping_roundtrip():
    ping = _valid_ping()
    payload = ping.model_dump(mode="json")
    rebuilt = AttentionSpec.model_validate(payload)
    assert rebuilt == ping
    assert rebuilt.card is CardType.PING


@pytest.mark.unit
def test_ping_requires_user_elicitation_source():
    with pytest.raises(ValidationError):
        AttentionSpec(
            title="Bad ping",
            description="Pings must use user_elicitation source.",
            card=CardType.PING,
            subject=Subject(name="x", type=SubjectType.EVENT),
            domain_tags=[DomainTag.REMINDER],
            sources=[Source(type=SourceType.WEB_EXA, params={"query": "x"})],
            extractor=Extractor(prompt="doesn't matter"),
            cadence=Cadence(
                type=CadenceType.ONE_SHOT, params={"trigger_at": "2026-05-01T18:00:00Z"}
            ),
            surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        )


@pytest.mark.unit
def test_ping_requires_one_shot_or_scheduled_cadence():
    with pytest.raises(ValidationError):
        AttentionSpec(
            title="Bad ping",
            description="Pings can't be ON_EVENT.",
            card=CardType.PING,
            subject=Subject(name="x", type=SubjectType.EVENT),
            domain_tags=[DomainTag.REMINDER],
            sources=[
                Source(
                    type=SourceType.USER_ELICITATION,
                    params={"question": "hi?"},
                )
            ],
            extractor=Extractor(prompt="fire the ping when triggered"),
            cadence=Cadence(
                type=CadenceType.ON_EVENT, params={"event_source": "foo"}
            ),
            surface_policy=SurfacePolicy(default=SurfaceLevel.NOTIFY),
        )


@pytest.mark.unit
def test_source_params_type_mismatch_rejected():
    with pytest.raises(ValidationError):
        Source(type=SourceType.API_OPENWEATHER, params={"query": "not-valid-for-weather"})


@pytest.mark.unit
def test_source_missing_required_param_rejected():
    with pytest.raises(ValidationError):
        Source(type=SourceType.WEB_EXA, params={})


@pytest.mark.unit
def test_cadence_on_event_requires_event_source():
    with pytest.raises(ValidationError):
        Cadence(type=CadenceType.ON_EVENT, params={})


@pytest.mark.unit
def test_cadence_scheduled_requires_cron_or_interval():
    with pytest.raises(ValidationError):
        Cadence(type=CadenceType.SCHEDULED, params={"foo": "bar"})
    Cadence(type=CadenceType.SCHEDULED, params={"cron": "*/5 * * * *"})
    Cadence(type=CadenceType.SCHEDULED, params={"interval_seconds": 300})


@pytest.mark.unit
def test_one_shot_requires_trigger_at():
    with pytest.raises(ValidationError):
        Cadence(type=CadenceType.ONE_SHOT, params={})
    Cadence(type=CadenceType.ONE_SHOT, params={"trigger_at": "2026-05-01T09:00:00Z"})


@pytest.mark.unit
def test_surface_policy_escalations_optional_with_default_empty():
    sp = SurfacePolicy(default=SurfaceLevel.DIGEST)
    assert sp.escalations == []
    sp_with = SurfacePolicy(
        default=SurfaceLevel.SILENT,
        escalations=[
            SurfaceEscalation(condition="consecutive_misses >= 3", level=SurfaceLevel.NOTIFY)
        ],
    )
    assert sp_with.escalations[0].level is SurfaceLevel.NOTIFY


@pytest.mark.unit
def test_resolve_if_and_urgent_if_independent():
    sp = SurfacePolicy(
        default=SurfaceLevel.DIGEST,
        urgent_if="event_type == 'funding'",
        resolve_if="days_since_activity > 21",
    )
    assert sp.urgent_if and sp.resolve_if


@pytest.mark.unit
def test_dedup_defaults_and_bounds():
    assert Dedup().window_size == 100
    with pytest.raises(ValidationError):
        Dedup(window_size=0)


@pytest.mark.unit
def test_relevance_threshold_bounds():
    payload = _valid_spec().model_dump(mode="json")
    payload["relevance_threshold"] = 1.5
    with pytest.raises(ValidationError):
        AttentionSpec.model_validate(payload)
    payload["relevance_threshold"] = -0.1
    with pytest.raises(ValidationError):
        AttentionSpec.model_validate(payload)


@pytest.mark.unit
def test_empty_sources_rejected():
    payload = _valid_spec().model_dump(mode="json")
    payload["sources"] = []
    with pytest.raises(ValidationError):
        AttentionSpec.model_validate(payload)


@pytest.mark.unit
def test_empty_domain_tags_rejected():
    payload = _valid_spec().model_dump(mode="json")
    payload["domain_tags"] = []
    with pytest.raises(ValidationError):
        AttentionSpec.model_validate(payload)


@pytest.mark.unit
def test_attention_record_constructs_with_shadow_state():
    spec = _valid_spec()
    record = Attention(
        user_id=uuid4(),
        spec=spec,
        origin=AttentionOrigin.SHADOW_INFERRED,
        created_at=datetime.now(timezone.utc),
        status=AttentionStatus.SHADOW,
        shadow_state=ShadowState(max_ticks=5, priority="medium"),
    )
    assert record.status is AttentionStatus.SHADOW
    assert record.shadow_state is not None
    assert record.shadow_state.tick_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("card", list(CardType))
def test_all_cards_have_derived_output_schema(card):
    if card is CardType.PING:
        spec = _valid_ping()
    else:
        spec = _valid_spec()
        # Mutate card field via revalidation (validate_assignment=True).
        payload = spec.model_dump(mode="json")
        payload["card"] = card.value
        spec = AttentionSpec.model_validate(payload)
    assert spec.output_schema["type"] == "object"
