"""dashboard_manifests — latest brain-emitted DashboardPlan per user.

One row per user, upserted by ``backend.dashboard.compose.compose_manifest``.
The plan_jsonb column is the wire format the frontend reads.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_manifests",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column(
            "plan_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("trigger", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("dashboard_manifests")
