"""Attention Harness.

End-to-end pipeline that turns natural-language user intents into executable
AttentionSpec JSON, runs a dry-run preview against historical data, and
surfaces a confirmable artifact.

Pipeline: intent -> normalize -> retrieve -> author -> validate -> dry_run.

Guiding principle: Donna watches AMBIENT SIGNAL only (email, calendar,
shipments, news, releases, tweets). Never user-organized workspaces
(Notion, Linear, Airtable, Trello, Asana, ClickUp).
"""

from donna.attention.schema import (
    Attention,
    AttentionOrigin,
    AttentionSpec,
    AttentionStatus,
    Cadence,
    Dedup,
    Extractor,
    NudgePolicy,
    ShadowState,
    Source,
    Subject,
    SurfaceEscalation,
    SurfacePolicy,
    UserEngagement,
)
from donna.attention.vocabulary import (
    CadenceType,
    CardType,
    DomainTag,
    SourceType,
    SubjectType,
    SurfaceLevel,
    output_schema_for_card,
)

__all__ = [
    "Attention",
    "AttentionOrigin",
    "AttentionSpec",
    "AttentionStatus",
    "Cadence",
    "CadenceType",
    "CardType",
    "Dedup",
    "DomainTag",
    "Extractor",
    "NudgePolicy",
    "ShadowState",
    "Source",
    "SourceType",
    "Subject",
    "SubjectType",
    "SurfaceEscalation",
    "SurfaceLevel",
    "SurfacePolicy",
    "UserEngagement",
    "output_schema_for_card",
]
