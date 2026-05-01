"""Backfill open_loops → attentions(card='open_loop') for the consolidation.

Phase 1b of the open_loops → attentions merge. Phase 1a wired dual-write
on new ``track_open_loop`` / ``close_open_loop`` calls. This migration
catches up the historical rows so both tables hold the same content
before any reader is switched in Phase 1c.

Idempotent: re-running only inserts open_loops that don't already have a
mirror row in attentions (matched via ``payload->>'mirror_open_loop_id'``).
Non-destructive: never touches the open_loops table.
Reversible: downgrade deletes only mirror-tagged rows
(``payload->>'mirror_source' = 'open_loops'``).

Status mapping:
  - open_loops.status='active'  → attentions.status='live'
  - open_loops.status='closed'  → attentions.status='resolved'
  - anything else (defensive)   → attentions.status='live'

Title (subject.name) is truncated to 80 chars; the full content is
preserved in payload.spec.rationale so no information is lost.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-01
"""
from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


_BACKFILL_SQL = """
INSERT INTO attentions (
    id, user_id, title, card, cadence_type, origin, status,
    payload, created_at, updated_at
)
SELECT
    gen_random_uuid()::text                   AS id,
    ol.user_id                                AS user_id,
    LEFT(ol.content, 80)                      AS title,
    'open_loop'                               AS card,
    'one_shot'                                AS cadence_type,
    'user_explicit'                           AS origin,
    CASE
        WHEN ol.status = 'active' THEN 'live'
        WHEN ol.status = 'closed' THEN 'resolved'
        ELSE 'live'
    END                                        AS status,
    jsonb_build_object(
        'spec', jsonb_build_object(
            'card', 'open_loop',
            'subject', jsonb_build_object(
                'name', LEFT(ol.content, 80),
                'type', 'open_loop_thread'
            ),
            'rationale', ol.content,
            'due_at', CASE
                WHEN ol.due_at IS NULL THEN NULL
                ELSE to_char(ol.due_at, 'YYYY-MM-DD"T"HH24:MI:SS')
            END
        ),
        'mirror_source', 'open_loops',
        'mirror_open_loop_id', ol.id,
        'source_message', ol.source_message
    )                                          AS payload,
    ol.created_at                              AS created_at,
    ol.created_at                              AS updated_at
FROM open_loops ol
WHERE NOT EXISTS (
    SELECT 1 FROM attentions a
    WHERE a.card = 'open_loop'
      AND a.payload->>'mirror_open_loop_id' = ol.id
);
"""


_DOWNGRADE_SQL = """
DELETE FROM attentions
WHERE card = 'open_loop'
  AND payload->>'mirror_source' = 'open_loops';
"""


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
