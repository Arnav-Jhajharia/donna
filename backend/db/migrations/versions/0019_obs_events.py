"""Add obs_events table — DB-backed event store for /observe.

Replaces the local-filesystem ``.donna/events.jsonl`` log as the source
of truth for the dashboard's observability surface. Files don't survive
across the Railway-pod / Vercel boundary, so /observe in production was
reading an empty file. DB rows let the brain (Railway) emit and the
dashboard (Vercel) read against the same Postgres.

Schema mirrors the JSONL line shape:
- ``event`` — short type tag (turn.start / turn.end / tool.call / hook.deny / memory.op / ...)
- ``ts`` — when the event was emitted (NOT created_at; the brain timestamps it)
- ``turn_id`` / ``user_id`` — nullable; some events (hook.deny) come without a turn
- ``payload`` — full JSONB blob with the rest of the keys

Indexes:
- (turn_id) for "show me this turn" queries
- (user_id, ts) for the per-user timeline /observe renders
- (ts) for the global recent-events view

Retention: NOT enforced at the migration. A retention sweep lives in a
separate worker that drops events older than N days. Don't enforce it
schema-side — we want to be able to inspect old turns when debugging.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "obs_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=False),
            nullable=False,
            index=True,
        ),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True, index=True),
        sa.Column("user_id", sa.String(), nullable=True, index=True),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_obs_events_user_ts",
        "obs_events",
        ["user_id", "ts"],
    )
    op.create_index(
        "idx_obs_events_ts_event",
        "obs_events",
        ["ts", "event"],
    )


def downgrade() -> None:
    op.drop_index("idx_obs_events_ts_event", table_name="obs_events")
    op.drop_index("idx_obs_events_user_ts", table_name="obs_events")
    op.drop_table("obs_events")
