"""Postgres tables for the Attention primitive.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26

Mirrors the in-memory ``donna.attention.schema.Attention`` so brain tools
(running on the API service) and the schedule worker (running on a
separate Railway service) share a durable view of every attention. The
file-JSON store (``~/.donna/attentions.json``) stays in tree as a dev /
cli fallback; production paths dual-write to this table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attentions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("card", sa.String(), nullable=False),
        sa.Column("cadence_type", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'live'"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_surfaced_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_attentions_user_status",
        "attentions",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_attentions_user_card",
        "attentions",
        ["user_id", "card"],
    )

    op.create_table(
        "attention_ticks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "attention_id",
            sa.String(),
            sa.ForeignKey("attentions.id"),
            nullable=False,
        ),
        sa.Column(
            "at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("rendered_markdown", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "source_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_attention_ticks_attention_at",
        "attention_ticks",
        ["attention_id", "at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_attention_ticks_attention_at", table_name="attention_ticks"
    )
    op.drop_table("attention_ticks")
    op.drop_index("idx_attentions_user_card", table_name="attentions")
    op.drop_index("idx_attentions_user_status", table_name="attentions")
    op.drop_table("attentions")
