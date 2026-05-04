"""Proactive dispatch telemetry — Phase 1 counterfactual logging.

Revision ID: 0023_proactive_dispatch_telemetry
Revises: 0022
Create Date: 2026-05-04 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_proactive_dispatch_telemetry"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_dispatch_telemetry",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "event_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("speech_act", sa.String(), nullable=False),
        sa.Column("topic_key", sa.String(), nullable=False),
        sa.Column("tier1_score", sa.Float(), nullable=True),
        sa.Column("arbiter_decision", sa.String(), nullable=True),
        sa.Column("arbiter_reason", sa.String(), nullable=True),
        sa.Column("tier2_action", sa.String(), nullable=True),
        sa.Column("tier2_register", sa.String(), nullable=True),
        sa.Column("tier2_draft", sa.Text(), nullable=True),
        sa.Column("tier2_needs_tools", sa.Boolean(), nullable=True),
        sa.Column("tier2_channel_hint", sa.String(), nullable=True),
        sa.Column("tier2_reclassify", sa.String(), nullable=True),
        sa.Column(
            "tier3_invoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("tier3_outcome", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column(
            "counterfactual_legacy_outbound_count", sa.Integer(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_outcome", sa.String(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_draft", sa.Text(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_skip_reason", sa.Text(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_elapsed_ms", sa.Integer(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_error", sa.Text(), nullable=True
        ),
    )
    op.create_index(
        "idx_pdt_user_event_at",
        "proactive_dispatch_telemetry",
        ["user_id", "event_at"],
    )
    op.create_index(
        "idx_pdt_speech_act",
        "proactive_dispatch_telemetry",
        ["speech_act"],
    )
    op.create_index(
        "idx_pdt_topic_key",
        "proactive_dispatch_telemetry",
        ["topic_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pdt_topic_key", table_name="proactive_dispatch_telemetry"
    )
    op.drop_index(
        "idx_pdt_speech_act", table_name="proactive_dispatch_telemetry"
    )
    op.drop_index(
        "idx_pdt_user_event_at", table_name="proactive_dispatch_telemetry"
    )
    op.drop_table("proactive_dispatch_telemetry")
