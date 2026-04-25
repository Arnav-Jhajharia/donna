"""list_gmail_recent — recent emails from local mirror.

Read-only view over the EmailMessage table populated by the live webhook
ingest. No round-trip to Composio; this tool is the cheap path for "any new
mail?" / "what came in today?" questions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.memory.tools._shape import ToolResult, no_hits, ok
from db.models import EmailMessage
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
