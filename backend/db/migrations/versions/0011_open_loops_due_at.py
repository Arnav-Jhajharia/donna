"""Add ``due_at`` to open_loops for deadline-proposer support.

Optional, nullable. Existing rows stay unchanged. Populated by the
``track_open_loop`` tool when the user phrases a deadline ("by Friday",
"before noon"). The DeadlineProposer reads it to fire a PING when a
loop is approaching its deadline without acknowledgement.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "open_loops",
        sa.Column("due_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_open_loops_user_due_at",
        "open_loops",
        ["user_id", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_open_loops_user_due_at", table_name="open_loops")
    op.drop_column("open_loops", "due_at")
