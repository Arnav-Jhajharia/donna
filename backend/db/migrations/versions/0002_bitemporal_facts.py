"""Bi-temporal facts table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        sa.Column("object", sa.Text(), nullable=False),
        sa.Column("object_json", JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(), nullable=False, server_default="chat"),
        sa.Column("t_valid_from", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("t_valid_to", sa.DateTime(), nullable=True),
        sa.Column("t_recorded_from", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("t_recorded_to", sa.DateTime(), nullable=True),
        sa.Column("superseded_by", sa.String(), sa.ForeignKey("facts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_facts_user_subj_pred", "facts", ["user_id", "subject", "predicate"])
    op.create_index("idx_facts_user_valid_from", "facts", ["user_id", "t_valid_from"])
    op.create_index("idx_facts_user_recorded_from", "facts", ["user_id", "t_recorded_from"])


def downgrade() -> None:
    op.drop_index("idx_facts_user_recorded_from", table_name="facts")
    op.drop_index("idx_facts_user_valid_from", table_name="facts")
    op.drop_index("idx_facts_user_subj_pred", table_name="facts")
    op.drop_table("facts")
