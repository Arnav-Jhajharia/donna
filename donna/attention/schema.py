"""Pydantic v2 models for the Attention primitive (v2).

AttentionSpec is the LLM-authored JSON that defines what to watch, how to
extract updates, when to run, and how to surface output. The shape of the
update is fixed by `card` (EventStream | Tally | Brief | PrepDoc | OpenLoop |
Ping), so the LLM picks semantics, not schema.

Attention wraps a spec with runtime status, engagement, shadow bookkeeping.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from donna.attention.vocabulary import (
    SOURCE_PARAMS_MODELS,
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
    output_schema_for_card,
)


# -- Runtime enums -----------------------------------------------------------


class AttentionOrigin(str, Enum):
    USER_EXPLICIT = "user_explicit"
    SHADOW_INFERRED = "shadow_inferred"
    OFFER_ACCEPTED = "offer_accepted"


class AttentionStatus(str, Enum):
    INTENT = "intent"
    SPEC_DRAFTED = "spec_drafted"
    DRY_RUN_PENDING = "dry_run_pending"
    LIVE = "live"
    SHADOW = "shadow"
    OFFERED = "offered"
    PAUSED = "paused"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    REJECTED = "rejected"
    QUIETLY_ARCHIVED = "quietly_archived"


# -- Base --------------------------------------------------------------------


class _StrictBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


# -- Spec nested models ------------------------------------------------------


class Subject(_StrictBase):
    name: str = Field(min_length=1, max_length=140)
    type: SubjectType


class Source(_StrictBase):
    type: SourceType
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_params_against_type(self) -> "Source":
        params_model = SOURCE_PARAMS_MODELS.get(self.type)
        if params_model is None:
            raise ValueError(f"No params model registered for source type {self.type}")
        params_model.model_validate(self.params)
        return self


class Extractor(_StrictBase):
    """Card determines output_schema; prompt tells the extractor what to look for."""

    prompt: str = Field(min_length=10, max_length=4000)


class Cadence(_StrictBase):
    type: CadenceType
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_cadence_params(self) -> "Cadence":
        t = self.type
        p = self.params
        if t is CadenceType.ON_EVENT and "event_source" not in p:
            raise ValueError("ON_EVENT cadence requires event_source param")
        if t is CadenceType.SCHEDULED and "cron" not in p and "interval_seconds" not in p:
            raise ValueError("SCHEDULED cadence requires cron or interval_seconds")
        if t is CadenceType.ON_RELEVANCE and "related_entity" not in p:
            raise ValueError("ON_RELEVANCE cadence requires related_entity param")
        if t is CadenceType.ONE_SHOT and "trigger_at" not in p:
            raise ValueError("ONE_SHOT cadence requires trigger_at param")
        return self


class SurfaceEscalation(_StrictBase):
    """Conditional bump of surface level (e.g. promote DIGEST → URGENT if streak ≥ 3)."""

    condition: str = Field(min_length=2, max_length=400)
    level: SurfaceLevel


class NudgePolicy(_StrictBase):
    """If the card stays silent too long, nudge the user to act or supply data."""

    if_silent_for_seconds: int = Field(ge=60, le=60 * 60 * 24 * 90)
    nudge_via: str = Field(default="whatsapp", pattern=r"^(whatsapp|dashboard_flag)$")
    nudge_text: str | None = None


class SurfacePolicy(_StrictBase):
    default: SurfaceLevel
    urgent_if: str | None = None
    resolve_if: str | None = None
    escalations: list[SurfaceEscalation] = Field(default_factory=list, max_length=4)
    nudge_policy: NudgePolicy | None = None
    quiet_hours_respected: bool = True


class Dedup(_StrictBase):
    key: str = Field(default="id", min_length=1, max_length=80)
    window_size: int = Field(default=100, ge=1, le=5000)


class AttentionSpec(_StrictBase):
    title: str = Field(min_length=1, max_length=140)
    description: str = Field(min_length=1, max_length=400)

    card: CardType
    subject: Subject
    domain_tags: list[DomainTag] = Field(min_length=1, max_length=6)

    sources: list[Source] = Field(min_length=1, max_length=8)
    extractor: Extractor
    cadence: Cadence
    surface_policy: SurfacePolicy
    relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    dedup: Dedup = Field(default_factory=Dedup)

    promotion_criteria: str | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _card_specific_rules(self) -> "AttentionSpec":
        if self.card is CardType.PING:
            # Pings are degenerate: one-shot or scheduled, no ambient fanout.
            if self.cadence.type not in (CadenceType.ONE_SHOT, CadenceType.SCHEDULED):
                raise ValueError("PING card requires ONE_SHOT or SCHEDULED cadence")
            if len(self.sources) != 1 or self.sources[0].type is not SourceType.USER_ELICITATION:
                raise ValueError(
                    "PING card requires exactly one USER_ELICITATION source"
                )
        return self

    @property
    def output_schema(self) -> dict[str, Any]:
        """Derived from card; not LLM-authored."""
        return output_schema_for_card(self.card)


# -- Runtime record ----------------------------------------------------------


class UserEngagement(_StrictBase):
    accepts: int = 0
    dismisses: int = 0
    mutes: int = 0
    opens: int = 0
    last_accept_at: datetime | None = None
    last_dismiss_at: datetime | None = None
    last_mute_at: datetime | None = None


class ShadowState(_StrictBase):
    """Bookkeeping for shadow-mode attentions awaiting promotion to LIVE."""

    tick_count: int = 0
    max_ticks: int = Field(default=5, ge=1, le=100)
    priority: str = Field(default="low", pattern=r"^(low|medium|high)$")
    promotion_hits: int = 0


class Attention(_StrictBase):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    spec: AttentionSpec
    origin: AttentionOrigin
    origin_episode_id: UUID | None = None
    status: AttentionStatus = AttentionStatus.INTENT
    created_at: datetime
    last_update_at: datetime | None = None
    last_surfaced_at: datetime | None = None
    update_count: int = 0
    user_engagement: UserEngagement = Field(default_factory=UserEngagement)
    shadow_state: ShadowState | None = None
    parent_attention_id: UUID | None = None
