"""Image tool events table — feeds caps + observability for the image tool.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_tool_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("prompt_hash", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_image_events_user_created",
        "image_tool_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_image_events_user_created", table_name="image_tool_events"
    )
    op.drop_table("image_tool_events")
