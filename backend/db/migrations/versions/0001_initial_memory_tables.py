"""Initial memory tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("phone", sa.String(), unique=True, nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False, server_default="Asia/Singapore"),
        sa.Column("facts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("living_profile", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_proactive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_chat_user_created", "chat_messages", ["user_id", "created_at"])

    op.create_table(
        "observations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("instance_id", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("event_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("tags", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fields", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("enriched", JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(), nullable=False, server_default="chat"),
        sa.Column("lineage", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_obs_user_type_time", "observations", ["user_id", "type", "event_time"])
    op.create_index("idx_obs_user_time", "observations", ["user_id", "event_time"])

    op.create_table(
        "open_loops",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_loops_user_status", "open_loops", ["user_id", "status"])

    op.create_table(
        "procedural_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_rules_user_type", "procedural_rules", ["user_id", "type"])

    op.create_table(
        "calendar_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("google_event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_cal_user_start", "calendar_entries", ["user_id", "start_time"])


def downgrade() -> None:
    for tbl in (
        "calendar_entries",
        "procedural_rules",
        "open_loops",
        "observations",
        "chat_messages",
        "users",
    ):
        op.drop_table(tbl)
