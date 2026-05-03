"""Add integration_events table — generic proactive lane for non-google toolkits.

Captures any V3 ``composio.trigger.message`` event we don't have a dedicated
ingest path for (slack, notion, linear, github, ...). Storing the raw payload
gives the proactive dispatcher a uniform feed to score on without us having
to write a bespoke ingest handler per toolkit.

Read surface: a single table with ``user_id``, ``toolkit``, ``trigger_slug``
plus the JSON payload. Future scorers / spawners select by toolkit + recency.

Idempotency: ``source_ref`` is an opaque per-event key (slack ``ts``, notion
``page.id``, linear ``issue.identifier``, etc.). When present we DEDUPE on
``(user_id, toolkit, source_ref)`` so Composio retries don't double-write.
When absent we still insert (some events have no natural id).

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("toolkit", sa.String(), nullable=False),
        sa.Column("trigger_slug", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_integration_events_user_toolkit_created",
        "integration_events",
        ["user_id", "toolkit", "created_at"],
    )
    op.create_index(
        "idx_integration_events_unprocessed",
        "integration_events",
        ["user_id", "created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_index(
        "uq_integration_events_dedupe",
        "integration_events",
        ["user_id", "toolkit", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_integration_events_dedupe", table_name="integration_events"
    )
    op.drop_index(
        "idx_integration_events_unprocessed", table_name="integration_events"
    )
    op.drop_index(
        "idx_integration_events_user_toolkit_created",
        table_name="integration_events",
    )
    op.drop_table("integration_events")
