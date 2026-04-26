"""Cache the issued OAuth redirect URL on integrations rows.

Lets connect_integration return the same fresh URL when one is already
in flight (instead of burning Composio credits re-initiating the chain
on every nudge), and re-issue cleanly when the cached URL is stale.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("redirect_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "integrations",
        sa.Column("redirect_url_issued_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "redirect_url_issued_at")
    op.drop_column("integrations", "redirect_url")
