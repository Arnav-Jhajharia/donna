"""Features primitive — Phase 1 substrate.

Adds the ``features`` table that ties attentions + observations + cron +
dashboard cards + hooks + tools + integrations into one composable unit.
Existing primitives gain a NULLable ``feature_id`` FK so old rows keep
working untagged and new feature-installed rows carry a back-link.

Revision ID: 0024_features
Revises: 0023_proactive_telemetry
Create Date: 2026-05-04 12:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_features"
down_revision = "0023_proactive_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "features",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("template_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("surface", sa.String(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("tone", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        sa.Column(
            "installed_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column("paused_until", sa.DateTime(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("manifest_version", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_features_user_name"),
    )
    op.create_index(
        "idx_features_user_status",
        "features",
        ["user_id", "status"],
    )

    # FK columns on existing primitives. All NULLable — no backfill in
    # Phase 1; old rows simply carry feature_id IS NULL.
    op.add_column(
        "attentions",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("features.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "observations",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("features.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "donna_schedule",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("features.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "procedural_rules",
        sa.Column(
            "feature_id",
            sa.String(),
            sa.ForeignKey("features.id"),
            nullable=True,
        ),
    )

    # Partial indexes — only index rows that are feature-tagged. The vast
    # majority of pre-Phase-1 rows are NULL and don't need to be indexed.
    op.create_index(
        "idx_observations_feature",
        "observations",
        ["feature_id"],
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )
    op.create_index(
        "idx_attentions_feature",
        "attentions",
        ["feature_id"],
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )
    op.create_index(
        "idx_schedule_feature",
        "donna_schedule",
        ["feature_id"],
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_schedule_feature", table_name="donna_schedule")
    op.drop_index("idx_attentions_feature", table_name="attentions")
    op.drop_index("idx_observations_feature", table_name="observations")

    op.drop_column("procedural_rules", "feature_id")
    op.drop_column("donna_schedule", "feature_id")
    op.drop_column("observations", "feature_id")
    op.drop_column("attentions", "feature_id")

    op.drop_index("idx_features_user_status", table_name="features")
    op.drop_table("features")
