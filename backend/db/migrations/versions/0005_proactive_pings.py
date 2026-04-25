"""Proactive ping log for rate limiting.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_pings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("message_ref", sa.String(), nullable=True),
        sa.Column(
            "fired_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("suppressed_reason", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_pings_user_fired", "proactive_pings", ["user_id", "fired_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_pings_user_fired", table_name="proactive_pings")
    op.drop_table("proactive_pings")
