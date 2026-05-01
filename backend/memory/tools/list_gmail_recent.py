"""list_gmail_recent — recent emails from local mirror.

Read-only view over the EmailMessage table populated by the live webhook
ingest. No round-trip to Composio; this tool is the cheap path for "any new
mail?" / "what came in today?" questions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from db.models import EmailMessage, User
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List recent gmail messages from the user's mailbox (read from local "
    "mirror; webhook-fed). Use when:\n"
    "  - the user asks 'any new mail?', 'what came in today?', 'has X emailed?'\n"
    "  - you need to summarize today's inbox or the last few hours\n"
    "Do NOT use when:\n"
    "  - the user asks for a specific thread by sender or subject — use a more\n"
    "    targeted retrieval (future iteration) or read_gmail_thread\n"
    "  - the [INTEGRATIONS] block shows google_gmail as not_connected\n"
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "within_hours": {"type": "integer", "default": 24},
        "limit": {"type": "integer", "default": 20},
        "important_only": {"type": "boolean", "default": False},
    },
    "required": [],
}


def _session_factory():
    from backend.db.session import async_session

    return async_session


async def _read_bootstrap_state(user_id: str) -> str | None:
    """Returns the bootstrap pipeline status for the user, or None when
    no run has ever been recorded. Used to disambiguate an empty local
    mirror (no rows) from a not-yet-bootstrapped one."""
    async with _session_factory()() as s:
        u = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is None:
            return None
        runs = (u.living_profile or {}).get("bootstrap_runs") or {}
        return runs.get("last_status")


async def _gmail_is_connected(user_id: str) -> bool:
    """True iff the user has a connected google_gmail integration row.
    Avoids the "warming up" degraded path for users who never connected
    gmail (the local mirror is legitimately empty for them)."""
    from db.models import Integration

    async with _session_factory()() as s:
        row = (
            await s.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == "google")
                .where(Integration.product == "gmail")
            )
        ).scalar_one_or_none()
        return row is not None and row.status == "connected"


@instrument_memory_op("postgres.gmail")
async def list_gmail_recent(
    user_id: str,
    within_hours: int = 24,
    limit: int = 20,
    important_only: bool = False,
) -> ToolResult:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=within_hours
    )
    async with _session_factory()() as session:
        stmt = (
            select(EmailMessage)
            .where(EmailMessage.user_id == user_id)
            .where(EmailMessage.internal_date >= cutoff)
            .order_by(EmailMessage.internal_date.desc())
            .limit(limit)
        )
        if important_only:
            stmt = stmt.where(EmailMessage.is_important.is_(True))
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        # Distinguish "actually empty inbox" from "bootstrap hasn't run /
        # is still running / failed" so Donna doesn't lie to the user.
        # Only meaningful when gmail is actually connected; otherwise
        # there's no ingest pipeline to be waiting on.
        if await _gmail_is_connected(user_id):
            # `reason` is the user-facing line — Donna-voice so the wrapper
            # can forward it verbatim. Don't add explanatory prose; it's
            # what the user sees.
            bootstrap_state = await _read_bootstrap_state(user_id)
            if bootstrap_state == "running":
                return degraded(
                    "still pulling your mail in. give me 30-60 seconds, then ask again."
                )
            if bootstrap_state == "failed":
                return degraded(
                    "gmail ingest hit a snag. want me to retry?"
                )
            if bootstrap_state is None:
                # No bootstrap_runs entry -> never fired. OAuth completion
                # webhook missed and per-turn reconcile hasn't auto-spawned
                # bootstrap yet. Tell the user it's fresh, not broken.
                return degraded(
                    "gmail's connected but i haven't pulled anything in yet. give me a minute."
                )
            # bootstrap_state == "completed" → real empty window.
        return no_hits()

    return ok(
        {
            "messages": [
                {
                    "id": r.gmail_message_id,
                    "thread_id": r.thread_id,
                    "from": r.from_address,
                    "from_name": r.from_name,
                    "subject": r.subject,
                    "snippet": r.snippet,
                    "is_important": r.is_important,
                    "is_starred": r.is_starred,
                    "internal_date": r.internal_date.isoformat(),
                }
                for r in rows
            ]
        }
    )
