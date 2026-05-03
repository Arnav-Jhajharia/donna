"""search_gmail — targeted live search across the user's gmail.

Goes around the local mirror entirely: hits Composio's
``GMAIL_FETCH_EMAILS`` with a Gmail-search query (``from:``,
``subject:``, ``after:``, ``has:attachment``, etc.), pages a small
result set, and hydrates each hit. Local-mirror rows are reused when
present; misses fall through to ``fetch_gmail_message`` and persist
into the mirror so the next read is warm.

This is the tool to use when:
  - the user asks for a specific email by sender / subject / topic
    that may or may not be in the recent-window mirror
  - the user's request implies search semantics ("find that email
    from stripe", "did anyone reply to the design doc")
  - the local mirror likely doesn't have the row (older than a few
    days, or a thread the user only just thought to ask about)

Returns the same shape as ``list_gmail_recent`` so the brain can
treat the two interchangeably.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from db.models import EmailMessage
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)


DESCRIPTION = (
    "Targeted live search across the user's full gmail history (Composio "
    "→ Gmail API). Use when the user asks for a specific email by "
    "sender, subject, or topic — especially when the row isn't in the "
    "recent-window mirror. Accepts Gmail search syntax: ``from:`` / "
    "``to:`` / ``subject:`` / ``after:YYYY/MM/DD`` / "
    "``has:attachment`` / ``is:important``. Hits are persisted into "
    "the local mirror so the next read is warm. Use when:\n"
    "  - 'find the email from stripe last month'\n"
    "  - 'did anyone reply to the design doc'\n"
    "  - 'when was the last invoice from acme'\n"
    "Do NOT use for 'any new mail?' / 'what came in today?' (use "
    "list_gmail_recent — cheaper, mirror-only).\n"
    "Do NOT use when [INTEGRATIONS] shows google_gmail as not_connected."
)


INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Gmail search query. Examples: 'from:stripe.com', "
                "'subject:invoice after:2026/04/01', "
                "'from:saurabh has:attachment', "
                "'newer_than:7d label:important'."
            ),
        },
        "limit": {"type": "integer", "default": 10},
    },
}


def _session_factory():
    from backend.db.session import async_session

    return async_session


async def _gmail_is_connected(user_id: str) -> bool:
    """Avoid the live-search round trip when gmail isn't connected."""
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


async def _hydrate_from_mirror(
    user_id: str, gmail_ids: list[str]
) -> dict[str, EmailMessage]:
    """Bulk-load mirror rows for the requested ids."""
    if not gmail_ids:
        return {}
    async with _session_factory()() as session:
        rows = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.gmail_message_id.in_(gmail_ids))
            )
        ).scalars().all()
    return {r.gmail_message_id: r for r in rows}


async def _fetch_and_persist(
    user_id: str, gmail_id: str
) -> EmailMessage | None:
    """For an id missing from the mirror, fetch via Composio and ingest.

    Returns the persisted EmailMessage row or None on any error. Errors
    are logged but never raised — partial results are fine, the caller
    just shows what we have.
    """
    try:
        from backend.integrations.composio_client import ComposioClient
        from backend.integrations.gmail_ingest import ingest_gmail_message
        from config import settings
    except Exception:
        logger.exception("search_gmail: imports failed")
        return None

    try:
        client = ComposioClient(api_key=settings.composio_api_key or "")
        msg = await client.fetch_gmail_message(
            user_id=user_id, message_id=gmail_id, include_body=True
        )
        await ingest_gmail_message(user_id, msg)
    except Exception:
        logger.exception(
            "search_gmail: fetch failed user=%s id=%s", user_id, gmail_id
        )
        return None

    async with _session_factory()() as session:
        return (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.gmail_message_id == gmail_id)
            )
        ).scalar_one_or_none()


@instrument_memory_op("composio.gmail.search")
async def search_gmail(
    user_id: str,
    query: str,
    limit: int = 10,
) -> ToolResult:
    query = (query or "").strip()
    if not query:
        return no_hits()

    if not await _gmail_is_connected(user_id):
        return degraded("gmail isn't connected. tap connect first.")

    # Step 1: get matching message ids from Composio's live search.
    try:
        from backend.integrations.composio_client import ComposioClient
        from config import settings

        client = ComposioClient(api_key=settings.composio_api_key or "")
        ids, _next = await client.list_gmail_message_ids(
            user_id=user_id, query=query, max_results=max(1, min(limit, 25)),
        )
    except Exception:
        logger.exception("search_gmail: list ids failed user=%s q=%r", user_id, query)
        return degraded("gmail's slow on my end. try again in a sec.")

    if not ids:
        return no_hits()

    # Step 2: prefer local mirror rows; fall through to Composio fetch
    # for misses. Mirror keeps the result fresh for next time.
    mirror = await _hydrate_from_mirror(user_id, ids)
    rows: list[EmailMessage] = []
    for gid in ids:
        row = mirror.get(gid)
        if row is None:
            row = await _fetch_and_persist(user_id, gid)
        if row is not None:
            rows.append(row)

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
