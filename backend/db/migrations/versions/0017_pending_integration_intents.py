"""Add pending_integration_intents table.

Captures the user's original ask when ``connect_integration`` is called
mid-turn, so once OAuth lands we can fire a proactive brain turn that
*answers the original question* instead of leaving the user to re-prompt.

Lifecycle:
- enqueued by ``backend.integrations.pending_intents.enqueue_intent``
  when the model calls ``connect_integration(intent=...)``
- drained by ``backend.integrations.pending_intents.drain_for_toolkit``
  when ``oauth_watcher.mark_connected`` (or the webhook ingest path)
  flips an integration row to ``connected``
- a drained intent is marked ``status='fired'`` with ``fired_at`` set,
  so re-runs of the watcher don't double-fire

Why a dedicated table vs. piggy-backing on OpenLoop: an OpenLoop is the
user's promise to themselves ("call mom sometime"). A blocked intent is
"this turn needs an integration that's not connected yet" — Donna's
problem, not the user's. Conflating them is sloppy. Keep them separate.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_integration_intents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("toolkits", JSONB, nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("fired_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_pending_intents_user_status",
        "pending_integration_intents",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pending_intents_user_status",
        table_name="pending_integration_intents",
    )
    op.drop_table("pending_integration_intents")
