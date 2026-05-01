"""Gmail inbox Poller for ``card=event_stream`` attentions.

Reads from the local ``EmailMessage`` mirror (already populated by the
gmail webhook ingest pipeline) and emits one ``ObservationDraft`` per
new message that matches the attention's filter.

Why not call gmail directly: the mirror is already there, indexed,
deduped, and importance-classified by the live ingest pipeline. Hitting
it instead of the gmail API means zero quota burn AND we get the
``is_important`` signal (label-router output) for free.

Filter spec lives on ``AttentionSpec.sources[].params``:

    {
        "type": "gmail_inbox",
        "params": {
            "from_contains": "stripe.com",       # optional substring on sender
            "subject_contains": "refund",        # optional substring on subject
            "important_only": true,              # default false
            "lookback_hours": 24,                # default 24, hard cap 168
        }
    }

Cursor lives on ``AttentionRow.payload['poller_cursors']['gmail_inbox']``
and stores ``last_seen_internal_date`` (ISO). The poller's caller is
responsible for stamping the cursor after persistence — this module is
pure read.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from backend.memory.attention.pollers import ObservationDraft, register

logger = logging.getLogger(__name__)


SOURCE_TYPE = "gmail_inbox"

_LOOKBACK_DEFAULT_HOURS = 24
_LOOKBACK_MAX_HOURS = 168  # 7 days
_FETCH_LIMIT = 50


def _coerce_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _params_for(attention: Any) -> dict[str, Any]:
    """Extract the gmail_inbox source params from the spec, if present."""
    spec = getattr(attention, "spec", None)
    sources = getattr(spec, "sources", []) if spec else []
    for s in sources or []:
        s_type = getattr(s, "type", None)
        s_type_val = getattr(s_type, "value", s_type)
        if s_type_val != SOURCE_TYPE:
            continue
        params = getattr(s, "params", None)
        if isinstance(params, dict):
            return dict(params)
        if params is None:
            return {}
        # pydantic model
        try:
            return dict(params.model_dump())  # type: ignore[attr-defined]
        except Exception:
            return {}
    return {}


def _match_filters(
    *,
    from_addr: str,
    from_name: str,
    subject: str,
    is_important: bool,
    params: dict[str, Any],
) -> bool:
    """Apply spec filters. Empty/missing filter = match-all."""
    if params.get("important_only") and not is_important:
        return False

    fc = (params.get("from_contains") or "").lower().strip()
    if fc:
        haystack = f"{from_addr} {from_name}".lower()
        if fc not in haystack:
            return False

    sc = (params.get("subject_contains") or "").lower().strip()
    if sc and sc not in subject.lower():
        return False

    return True


def _lookback_cutoff(params: dict[str, Any]) -> datetime:
    raw = params.get("lookback_hours") or _LOOKBACK_DEFAULT_HOURS
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        hours = _LOOKBACK_DEFAULT_HOURS
    hours = max(1, min(hours, _LOOKBACK_MAX_HOURS))
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)


def _cursor_for(attention: Any) -> datetime | None:
    """Read the last-seen internal_date for this attention's gmail_inbox poll."""
    payload = getattr(attention, "_payload", None) or getattr(
        attention, "payload", None
    )
    if not isinstance(payload, dict):
        return None
    cursors = payload.get("poller_cursors") or {}
    raw = (cursors.get(SOURCE_TYPE) or {}).get("last_seen_internal_date")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d
    except Exception:
        return None


class GmailInboxPoller:
    """Pulls new gmail messages matching an attention's filter."""

    async def fetch(
        self, *, attention: Any, ctx: Any
    ) -> list[ObservationDraft]:
        from db.models import EmailMessage
        from db.session import async_session

        params = _params_for(attention)
        user_id = getattr(ctx, "user_id", "") or ""
        if not user_id:
            return []

        cutoff = _cursor_for(attention) or _lookback_cutoff(params)

        try:
            async with async_session() as session:
                stmt = (
                    select(EmailMessage)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.internal_date > cutoff)
                    .order_by(EmailMessage.internal_date.asc())
                    .limit(_FETCH_LIMIT)
                )
                rows = (await session.execute(stmt)).scalars().all()
        except Exception:
            logger.exception(
                "GmailInboxPoller: db read failed user=%s", user_id[:8]
            )
            return []

        drafts: list[ObservationDraft] = []
        for r in rows:
            from_addr = _coerce_str(r.from_address)
            from_name = _coerce_str(r.from_name)
            subject = _coerce_str(r.subject)
            if not _match_filters(
                from_addr=from_addr,
                from_name=from_name,
                subject=subject,
                is_important=bool(r.is_important),
                params=params,
            ):
                continue
            drafts.append(
                ObservationDraft(
                    type="email",
                    fields={
                        "gmail_message_id": r.gmail_message_id,
                        "thread_id": r.thread_id,
                        "from_address": from_addr,
                        "from_name": from_name,
                        "subject": subject,
                        "snippet": _coerce_str(r.snippet),
                        "is_important": bool(r.is_important),
                        "is_starred": bool(r.is_starred),
                        "internal_date": r.internal_date.isoformat()
                        if r.internal_date
                        else None,
                    },
                    raw=subject or _coerce_str(r.snippet),
                    tags={
                        "source_type": SOURCE_TYPE,
                        "from_contains": params.get("from_contains") or "",
                        "subject_contains": params.get("subject_contains") or "",
                    },
                    confidence=1.0,
                )
            )
        return drafts


# Register at import time. Idempotent — re-import won't double-register.
register(SOURCE_TYPE, GmailInboxPoller())
