"""Generic capture for V3 trigger events without a dedicated ingest path.

Composio's V3 webhook fires uniform ``composio.trigger.message`` envelopes
for every toolkit. Gmail and calendar already have bespoke ingest into
typed tables. Slack / notion / linear / github / others have no such home
yet, so we land them here in a single ``integration_events`` table for the
proactive dispatcher to score.

Two responsibilities:

1. ``record_event`` — idempotent insert with ``IntegrityError`` swallow on
   the (user_id, toolkit, source_ref) unique index. Composio retries are a
   normal part of the contract — never let a duplicate webhook produce a
   duplicate row.

2. ``toolkit_for_trigger_slug`` + ``source_ref_for`` — small mapping
   helpers that try to extract a stable per-event id from the inner
   payload. Every toolkit shape is different; we cover the common ones
   and fall back to ``None`` (insert-without-dedupe) when unsure.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from db.models import IntegrationEvent

logger = logging.getLogger(__name__)


def _session_factory():
    """Late import so test monkeypatching of ``async_session`` is honored."""
    from backend.db.session import async_session

    return async_session


# Trigger-slug prefix → canonical toolkit name. Drives both the row's
# ``toolkit`` column and the source_ref extractor's branch. Order matters
# only for slugs that share prefixes — keep most-specific first.
_TOOLKIT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("GOOGLECALENDAR", "calendar"),
    ("GMAIL", "gmail"),
    ("GOOGLEDRIVE", "drive"),
    ("SLACK", "slack"),
    ("NOTION", "notion"),
    ("LINEAR", "linear"),
    ("GITHUB", "github"),
    ("ASANA", "asana"),
    ("DISCORD", "discord"),
    ("TELEGRAM", "telegram"),
    ("HUBSPOT", "hubspot"),
)


def toolkit_for_trigger_slug(trigger_slug: str) -> str:
    """Best-effort toolkit name from a Composio trigger slug.

    Slug shape: ``<TOOLKIT>_<EVENT>_<MAYBE_SUFFIX>``. We match by prefix
    against a curated list. Unknown slugs return the lowercase first
    underscore-segment so we still get a reasonable bucket without having
    to ship a code change for every new toolkit.
    """
    if not trigger_slug:
        return "unknown"
    upper = trigger_slug.upper()
    for prefix, toolkit in _TOOLKIT_PREFIXES:
        if upper.startswith(prefix + "_") or upper == prefix:
            return toolkit
    return upper.split("_", 1)[0].lower() or "unknown"


def source_ref_for(toolkit: str, inner: dict[str, Any]) -> str | None:
    """Best-effort stable per-event id for dedupe.

    Returns ``None`` when the toolkit doesn't expose a clean id we can
    trust — the caller will then accept the (rare) duplicate insert risk
    rather than block the event entirely.
    """
    if not isinstance(inner, dict):
        return None

    if toolkit == "slack":
        # slack messages: ``ts`` is unique per channel; channel scopes it
        ts = inner.get("ts") or (inner.get("event") or {}).get("ts")
        channel = inner.get("channel") or (inner.get("event") or {}).get("channel")
        if ts and channel:
            return f"{channel}:{ts}"
        if ts:
            return str(ts)

    if toolkit == "notion":
        # page / database / block updates carry id directly
        page = inner.get("page") or {}
        if isinstance(page, dict) and page.get("id"):
            return f"page:{page['id']}"
        if inner.get("id"):
            return str(inner["id"])

    if toolkit == "linear":
        issue = inner.get("issue") or inner.get("data") or {}
        if isinstance(issue, dict):
            ident = issue.get("identifier") or issue.get("id")
            if ident:
                return str(ident)
        if inner.get("id"):
            return str(inner["id"])

    if toolkit == "github":
        # delivery id is ideal but rarely in the payload; fall back to
        # event-typed id (issue/pr/comment number)
        for key in ("delivery", "delivery_id", "id"):
            if inner.get(key):
                return str(inner[key])

    # Generic fallback — most toolkits expose ``id`` somewhere.
    if inner.get("id"):
        return str(inner["id"])
    return None


async def record_event(
    *,
    user_id: str,
    trigger_slug: str,
    inner: dict[str, Any],
    toolkit: str | None = None,
) -> bool:
    """Insert a row in ``integration_events``. Returns True on insert,
    False on dedupe-conflict or DB error.

    Errors are logged but never raised — the webhook handler still 200s
    regardless so Composio doesn't retry the entire envelope.
    """
    if not user_id or not trigger_slug:
        return False
    toolkit = toolkit or toolkit_for_trigger_slug(trigger_slug)
    source_ref = source_ref_for(toolkit, inner)

    try:
        async with _session_factory()() as session:
            row = IntegrationEvent(
                user_id=user_id,
                toolkit=toolkit,
                trigger_slug=trigger_slug.upper(),
                payload=inner if isinstance(inner, dict) else {"_raw": inner},
                source_ref=source_ref,
            )
            session.add(row)
            await session.commit()
            return True
    except IntegrityError:
        logger.info(
            "record_event: dedupe-skip user=%s toolkit=%s source_ref=%s",
            user_id, toolkit, source_ref,
        )
        return False
    except Exception:
        logger.exception(
            "record_event: insert failed user=%s toolkit=%s slug=%s",
            user_id, toolkit, trigger_slug,
        )
        return False
