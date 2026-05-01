"""Add email_intelligence table.

Stores Haiku-enriched view of important inbound EmailMessage rows:
classification, draft_text, key_points, recommended_action, and
cross-integration context links. Drives the morning brief, the
[INTEGRATIONS SIGNALS] block's "drafts ready" count, and the
dashboard's pending-review surface.

Conservative agency: ``sent_draft_at`` and ``user_action`` are written
only when the user explicitly confirms. Drafts are never auto-sent.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_intelligence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "email_message_id",
            sa.String(),
            sa.ForeignKey("email_messages.id"),
            nullable=False,
        ),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column(
            "urgency",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "key_points",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("draft_confidence", sa.Float(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column(
            "context_links",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("sent_draft_at", sa.DateTime(), nullable=True),
        sa.Column("user_action", sa.String(), nullable=True),
    )
    op.create_index(
        "uq_email_intel_message",
        "email_intelligence",
        ["user_id", "email_message_id"],
        unique=True,
    )
    op.create_index(
        "idx_email_intel_user_processed",
        "email_intelligence",
        ["user_id", "processed_at"],
    )
    op.create_index(
        "idx_email_intel_user_unhandled",
        "email_intelligence",
        ["user_id", "processed_at"],
        postgresql_where=sa.text(
            "sent_draft_at IS NULL AND user_action IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_email_intel_user_unhandled", table_name="email_intelligence"
    )
    op.drop_index(
        "idx_email_intel_user_processed", table_name="email_intelligence"
    )
    op.drop_index("uq_email_intel_message", table_name="email_intelligence")
    op.drop_table("email_intelligence")
