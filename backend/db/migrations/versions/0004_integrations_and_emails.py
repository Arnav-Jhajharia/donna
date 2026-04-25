"""Integrations + email_messages tables for Composio Google integration.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("composio_connection_id", sa.String(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_integrations_user_provider_product",
        "integrations",
        ["user_id", "provider", "product"],
        unique=True,
    )

    op.create_table(
        "email_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("gmail_message_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("from_address", sa.String(), nullable=False),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column(
            "to_addresses",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "cc_addresses",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "body_stored", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "labels",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "is_important", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_starred", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_sent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("ingest_depth", sa.String(), nullable=False),
        sa.Column("internal_date", sa.DateTime(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_email_user_msg",
        "email_messages",
        ["user_id", "gmail_message_id"],
        unique=True,
    )
    op.create_index(
        "idx_emails_user_date", "email_messages", ["user_id", "internal_date"]
    )
    op.create_index(
        "idx_emails_user_thread", "email_messages", ["user_id", "thread_id"]
    )
    op.create_index(
        "idx_emails_user_important",
        "email_messages",
        ["user_id", "is_important"],
        postgresql_where=sa.text("is_important"),
    )


def downgrade() -> None:
    op.drop_index("idx_emails_user_important", table_name="email_messages")
    op.drop_index("idx_emails_user_thread", table_name="email_messages")
    op.drop_index("idx_emails_user_date", table_name="email_messages")
    op.drop_index("uq_email_user_msg", table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_index(
        "uq_integrations_user_provider_product", table_name="integrations"
    )
    op.drop_table("integrations")
