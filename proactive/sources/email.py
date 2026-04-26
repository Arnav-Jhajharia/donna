"""Email source adapter for the unified proactive pipeline.

Wraps the existing Tier 1 email scorer + ``NormalizedGmailMessage`` into a
``ProactiveEvent``. Also pre-fetches deterministic signals the Tier 1 scorer
needs (recent sent thread ids) so the judge sees consistent context.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from proactive.events import ProactiveEvent, make_event_from_email

logger = logging.getLogger(__name__)

_RECENT_SENT_LOOKBACK = 50


def _session_factory():
    # Lazy import — keeps test monkeypatches of ``async_session`` honored.
    from backend.db.session import async_session

    return async_session


async def fetch_recent_sent_thread_ids(user_id: str) -> set[str]:
    """Return thread ids of the user's last N sent gmail messages.

    Used by the Tier 1 scorer's ``ScoringContext`` so the dispatcher does
    not re-surface threads the user already replied to. Cheap query
    (one table, indexed by user + thread). Failures degrade to an empty
    set so the proactive path stays alive.
    """
    try:
        from db.models import EmailMessage

        async with _session_factory()() as session:
            rows = (
                await session.execute(
                    select(EmailMessage.thread_id)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.is_sent.is_(True))
                    .order_by(EmailMessage.internal_date.desc())
                    .limit(_RECENT_SENT_LOOKBACK)
                )
            ).all()
        return {row[0] for row in rows if row and row[0]}
    except Exception:
        logger.exception(
            "email source: recent_sent_thread_ids fetch failed user=%s",
            user_id,
        )
        return set()


def make_event(user_id: str, msg: Any, score: Any) -> ProactiveEvent:
    """Build a ``ProactiveEvent`` for an inbound gmail message.

    Thin shim over ``proactive.events.make_event_from_email`` so callers
    can import ``proactive.sources.email.make_event`` consistently with
    future source adapters.
    """
    return make_event_from_email(user_id, msg, score)
