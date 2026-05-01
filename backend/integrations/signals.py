"""[INTEGRATIONS SIGNALS] block — content-rich signal lines per integration.

Sits below [INTEGRATIONS] in the wrapped user prompt. Carries cheap,
precomputed signals (count + top item) per connected integration so
the model has a concrete reason to reach for the typed read tools
(list_gmail_recent, read_gmail_thread, list_calendar) without bodies
landing in the prefix.

All queries are local-DB-only (no Composio, no LLM, no network). Any
failure or empty signal returns an empty string from the top-level
renderer so the caller can skip injection without a try/except.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select

from db.models import EmailMessage

logger = logging.getLogger(__name__)

_GMAIL_LOOKBACK_HOURS = 24
_SUBJECT_CAP = 80


def _session_factory():
    """Lazy import mirrors backend/memory/tools/list_gmail_recent.py.

    Keeps this module importable in unit tests that don't bring up the
    full backend.db package.
    """
    from backend.db.session import async_session

    return async_session


def _short_sender(from_name: str | None, from_address: str | None) -> str:
    name = (from_name or "").strip()
    if name:
        return name
    addr = (from_address or "").strip()
    if not addr:
        return "unknown"
    if "<" in addr and ">" in addr:
        bracketed = addr.split("<", 1)[1].rstrip(">")
        addr = bracketed
    if "@" in addr:
        return addr.split("@", 1)[0]
    return addr


def _format_age(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


async def gmail_signal_line(
    user_id: str,
    *,
    now: datetime | None = None,
) -> str | None:
    """One-line signal of recent important inbound mail.

    Format: ``gmail: N important (24h), top: <sender> "<subject>" <age>``.
    Returns ``None`` when there's nothing worth surfacing or on any failure.
    Uses ``internal_date`` (gmail's view of when the message arrived) so
    the signal matches what the user would see in the inbox.
    """
    if not user_id:
        return None
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=_GMAIL_LOOKBACK_HOURS)

    try:
        async with _session_factory()() as session:
            count_stmt = (
                select(func.count())
                .select_from(EmailMessage)
                .where(
                    EmailMessage.user_id == user_id,
                    EmailMessage.is_important.is_(True),
                    EmailMessage.is_sent.is_(False),
                    EmailMessage.internal_date >= cutoff,
                )
            )
            total = (await session.execute(count_stmt)).scalar_one()
            if not total:
                return None

            top_stmt = (
                select(EmailMessage)
                .where(
                    EmailMessage.user_id == user_id,
                    EmailMessage.is_important.is_(True),
                    EmailMessage.is_sent.is_(False),
                    EmailMessage.internal_date >= cutoff,
                )
                .order_by(desc(EmailMessage.internal_date))
                .limit(1)
            )
            top = (await session.execute(top_stmt)).scalar_one_or_none()
    except Exception:
        logger.exception("gmail_signal_line: query failed user=%s", user_id)
        return None

    if top is None:
        return f"gmail: {total} important unread (24h)"

    sender = _short_sender(top.from_name, top.from_address)
    subject = (top.subject or "").strip()
    if len(subject) > _SUBJECT_CAP:
        subject = subject[: _SUBJECT_CAP - 1].rstrip() + "…"
    age = _format_age(now - top.internal_date)

    if subject:
        return (
            f'gmail: {total} important unread (24h), '
            f'top: {sender} "{subject}" {age}'
        )
    return f"gmail: {total} important unread (24h), top: {sender} {age}"


async def render_integrations_signals_block(
    user_id: str,
    *,
    now: datetime | None = None,
) -> str:
    """Render the ``[INTEGRATIONS SIGNALS]`` block.

    Returns an empty string when no integration has anything to surface,
    so the caller can do ``if block: lines.append(block)`` without
    additional gating.
    """
    if not user_id:
        return ""
    lines: list[str] = []

    gmail = await gmail_signal_line(user_id, now=now)
    if gmail:
        lines.append(f"  {gmail}")

    if not lines:
        return ""
    return "\n".join(["[INTEGRATIONS SIGNALS]", *lines])
