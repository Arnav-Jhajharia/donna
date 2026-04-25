"""Apply label-routing to a normalized gmail message and upsert mirror.

Idempotent: re-ingesting the same gmail_message_id refreshes label-derived
fields (since labels can change after delivery, e.g. user marks important).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.label_router import classify_depth
from backend.integrations.proactive_email_trigger import maybe_surface_email
from db.models import EmailMessage

logger = logging.getLogger(__name__)


def _session_factory():
    from backend.db.session import async_session

    return async_session


async def ingest_gmail_message(
    user_id: str, msg: NormalizedGmailMessage
) -> None:
    depth = classify_depth(
        labels=msg.labels,
        is_starred=msg.is_starred,
        is_important=msg.is_important,
        is_sent=msg.is_sent,
    )
    if depth in ("ignore", "aggregate"):
        return

    body_stored = depth == "full" and msg.body_text is not None
    body_text = msg.body_text if body_stored else None

    async with _session_factory()() as session:
        existing = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.gmail_message_id == msg.gmail_message_id)
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                EmailMessage(
                    user_id=user_id,
                    gmail_message_id=msg.gmail_message_id,
                    thread_id=msg.thread_id,
                    from_address=msg.from_address,
                    from_name=msg.from_name,
                    to_addresses=msg.to_addresses,
                    cc_addresses=msg.cc_addresses,
                    subject=msg.subject,
                    snippet=msg.snippet,
                    body_text=body_text,
                    body_stored=body_stored,
                    labels=msg.labels,
                    is_important=msg.is_important,
                    is_starred=msg.is_starred,
                    is_sent=msg.is_sent,
                    ingest_depth=depth,
                    internal_date=msg.internal_date,
                )
            )
        else:
            existing.labels = msg.labels
            existing.is_important = msg.is_important
            existing.is_starred = msg.is_starred
            existing.is_sent = msg.is_sent
            existing.snippet = msg.snippet
            existing.body_text = body_text
            existing.body_stored = body_stored
            existing.ingest_depth = depth

        await session.commit()

    # Fan out to the proactive email trigger only for rows we actually
    # stored. Failures here must not affect ingest durability.
    try:
        await maybe_surface_email(user_id, msg)
    except Exception:
        logger.exception(
            "ingest_gmail_message: proactive trigger failed user=%s msg=%s",
            user_id, msg.gmail_message_id,
        )
