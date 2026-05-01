"""Add is_shadow column to chat_messages.

Used by the proactive delivery layer to log "would have sent" drafts
without surfacing them to the user during shadow mode.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "is_shadow",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_chat_messages_user_shadow",
        "chat_messages",
        ["user_id", "is_shadow"],
        postgresql_where=sa.text("is_shadow = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_chat_messages_user_shadow", table_name="chat_messages"
    )
    op.drop_column("chat_messages", "is_shadow")
