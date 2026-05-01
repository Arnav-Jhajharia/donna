"""Proactive web search subsystem v1.

Tables:
- proactive_subscriptions: per-user durable subscription per intent_key
- proactive_signals: queue of Exa monitor hits awaiting drain
- proactive_ledger: persistent dedup TTL ledger
- proactive_daily_count: per-user-per-local-day move counter

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("intent_key", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("webset_id", sa.String(), nullable=True),
        sa.Column("monitor_id", sa.String(), nullable=True),
        sa.Column(
            "cadence", sa.String(), nullable=False, server_default="daily"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.UniqueConstraint(
            "user_id", "intent_key", name="uq_proactive_subs_user_intent"
        ),
    )
    op.create_index(
        "idx_proactive_subs_user_active",
        "proactive_subscriptions",
        ["user_id", "active"],
    )

    op.create_table(
        "proactive_signals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "subscription_id",
            sa.String(),
            sa.ForeignKey("proactive_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("intent_key", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("arrived_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_proactive_signals_user_pending",
        "proactive_signals",
        ["user_id", "arrived_at"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )

    op.create_table(
        "proactive_ledger",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("fired_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "dedup_key", name="pk_proactive_ledger"
        ),
    )
    op.create_index(
        "idx_proactive_ledger_fired",
        "proactive_ledger",
        ["user_id", "fired_at"],
    )

    op.create_table(
        "proactive_daily_count",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("local_date", sa.String(), nullable=False),
        sa.Column(
            "count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "local_date", name="pk_proactive_daily_count"
        ),
    )


def downgrade() -> None:
    op.drop_table("proactive_daily_count")
    op.drop_index(
        "idx_proactive_ledger_fired", table_name="proactive_ledger"
    )
    op.drop_table("proactive_ledger")
    op.drop_index(
        "idx_proactive_signals_user_pending",
        table_name="proactive_signals",
    )
    op.drop_table("proactive_signals")
    op.drop_index(
        "idx_proactive_subs_user_active",
        table_name="proactive_subscriptions",
    )
    op.drop_table("proactive_subscriptions")
