"""Proactive engine v1: pending_proactive_notes table + topic_key on pings.

Phase 0 of the tiered proactive engine. Adds the hold-lane storage and
extends ProactivePing with the per-topic dedup column the unified arbiter
reads.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proactive_pings",
        sa.Column("topic_key", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_pings_user_topic_fired",
        "proactive_pings",
        ["user_id", "topic_key", "fired_at"],
        postgresql_where=sa.text("topic_key IS NOT NULL"),
    )

    op.create_table(
        "pending_proactive_notes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("topic_key", sa.String(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column(
            "tie_in",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_pending_user_status_created",
        "pending_proactive_notes",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "idx_pending_user_topic",
        "pending_proactive_notes",
        ["user_id", "topic_key"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pending_user_topic", table_name="pending_proactive_notes"
    )
    op.drop_index(
        "idx_pending_user_status_created",
        table_name="pending_proactive_notes",
    )
    op.drop_table("pending_proactive_notes")

    op.drop_index("idx_pings_user_topic_fired", table_name="proactive_pings")
    op.drop_column("proactive_pings", "topic_key")
