"""read_gmail_thread — full bodies for one thread, lazy-fetch on demand.

Local mirror is the source of truth. When a row's body was filtered out at
ingest (label policy stored metadata only), this tool round-trips Composio
once, persists the body, and returns it. If Composio is unreachable, the
message surfaces with `body=None` rather than failing the whole thread.
"""
from __future__ import annotations

from sqlalchemy import select

from backend.integrations.composio_client import ComposioClient
from backend.memory.tools._shape import ToolResult, no_hits, ok
from config import settings
from db.models import EmailMessage
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Fetch all messages in a single gmail thread by thread_id, with full "
    "bodies. If a message body is not in the local mirror (label policy "
    "kept only metadata), this tool lazy-fetches it from Composio and "
    "persists it. Use when:\n"
    "  - the user asks about a specific thread you've already shown them\n"
    "  - you need full content to compose a reply or summarize a conversation\n"
    "Do NOT use when:\n"
    "  - the user asks 'what's new in my inbox?' — use list_gmail_recent\n"
    "  - the [INTEGRATIONS] block shows google_gmail as not_connected\n"
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string"},
    },
    "required": ["thread_id"],
}


def _session_factory():
    from backend.db.session import async_session

    return async_session


async def _persist_body(user_id: str, message_id: str, body: str | None) -> None:
    if body is None:
        return
    factory = _session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.gmail_message_id == message_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.body_text = body
        row.body_stored = True
        row.ingest_depth = "full"
        await session.commit()


@instrument_memory_op("postgres.gmail.thread")
async def read_gmail_thread(user_id: str, thread_id: str) -> ToolResult:
    factory = _session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.thread_id == thread_id)
                .order_by(EmailMessage.internal_date.asc())
            )
        ).scalars().all()

    if not rows:
        return no_hits()

    client = ComposioClient(api_key=settings.composio_api_key or "")
    messages: list[dict] = []
    for row in rows:
        body = row.body_text if row.body_stored else None
        if body is None:
            try:
                msg = await client.fetch_gmail_message(
                    user_id=user_id,
                    message_id=row.gmail_message_id,
                    include_body=True,
                )
            except Exception:
                msg = None
            if msg is not None and msg.body_text is not None:
                body = msg.body_text
                await _persist_body(user_id, row.gmail_message_id, body)

        messages.append(
            {
                "id": row.gmail_message_id,
                "thread_id": row.thread_id,
                "from": row.from_address,
                "from_name": row.from_name,
                "subject": row.subject,
                "internal_date": row.internal_date.isoformat(),
                "body": body,
            }
        )

    return ok({"messages": messages})
