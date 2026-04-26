"""Link donna_schedule rows to attentions and carry cadence for re-enqueue.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "donna_schedule",
        sa.Column("attention_id", sa.String(), nullable=True),
    )
    op.add_column(
        "donna_schedule",
        sa.Column("recurrence_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "idx_schedule_attention_unfired",
        "donna_schedule",
        ["attention_id", "fired"],
    )


def downgrade() -> None:
    op.drop_index("idx_schedule_attention_unfired", table_name="donna_schedule")
    op.drop_column("donna_schedule", "recurrence_meta")
    op.drop_column("donna_schedule", "attention_id")
