"""auth_otps — single-use 6-digit login codes for the WhatsApp fallback.

Codes are sha256-hashed at insert; rows are deleted on verify or on
expiry (10 min TTL). Cap of 3 active per user enforced in app code.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_otps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_auth_otps_user_expires",
        "auth_otps",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_otps_user_expires", table_name="auth_otps")
    op.drop_table("auth_otps")
