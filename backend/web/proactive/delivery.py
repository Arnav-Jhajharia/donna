"""Delivery layer for proactive verdicts.

Two modes:
- ``shadow``: writes a ``chat_messages`` row with ``is_shadow=True``,
  does NOT send WhatsApp. The drafts surface in the dashboard for
  calibration but the user never sees them.
- ``live``: writes ``is_shadow=False`` and dispatches WhatsApp via
  ``delivery.whatsapp.WhatsAppChannel``.

Caller chooses mode per user. New users default to shadow for ~14 days
while we calibrate the judge - after that the operator flips them by
toggling ``users.living_profile['proactive_delivery_mode'] = 'live'``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select

from backend.web.proactive.judge import JudgeVerdict
from backend.web.proactive.types import ProactiveResult
from db.models import ChatMessage, User
from db.session import async_session

logger = logging.getLogger(__name__)

DeliveryMode = Literal["shadow", "live"]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_whatsapp_channel():
    """Indirection so tests can monkeypatch the channel constructor."""
    from delivery.whatsapp import WhatsAppChannel
    return WhatsAppChannel()


async def _user_phone(user_id: str) -> str | None:
    async with async_session() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    return getattr(u, "phone", None) if u else None


async def deliver_drafts(
    *,
    user_id: str,
    verdicts: list[tuple[ProactiveResult, JudgeVerdict]],
    mode: DeliveryMode = "shadow",
) -> int:
    """Persist + dispatch greenlit drafts. Returns number sent.

    Silence verdicts are dropped silently (they never had a draft).
    Failures during dispatch are logged but not raised - the row is
    still persisted with ``is_shadow=`` matching the requested mode so we
    have an audit trail either way.
    """
    sends = [
        (r, v.draft) for r, v in verdicts
        if v.decision == "send" and v.draft.strip()
    ]
    if not sends:
        return 0

    delivered = 0
    drafts_for_wa: list[str] = []

    async with async_session() as session:
        for result, draft in sends:
            row = ChatMessage(
                user_id=user_id,
                role="assistant",
                content=draft,
                is_proactive=True,
                is_shadow=(mode == "shadow"),
                created_at=_utcnow_naive(),
            )
            session.add(row)
            await session.flush()
            try:
                from donna_runtime.observability import emit

                emit(
                    "proactive.delivered",
                    user_id=user_id,
                    source="webset_subscription",
                    surface="web/proactive/delivery",
                    message_id=row.id,
                    mode=mode,
                    is_shadow=(mode == "shadow"),
                    intent_key=getattr(result, "intent_key", None),
                    signal_id=getattr(result, "signal_id", None),
                    subscription_id=getattr(result, "subscription_id", None),
                    draft_preview=(draft or "")[:200],
                )
            except Exception:
                logger.exception("deliver_drafts: emit failed user=%s", user_id[:8])
            delivered += 1
            if mode == "live":
                drafts_for_wa.append(draft)
        await session.commit()

    if mode == "live" and drafts_for_wa:
        phone = await _user_phone(user_id)
        if not phone:
            logger.warning(
                "deliver_drafts: live mode but user has no phone user=%s",
                user_id[:8],
            )
            return delivered
        try:
            channel = _get_whatsapp_channel()
            await channel.send_many(phone, drafts_for_wa)
        except Exception:
            logger.exception(
                "deliver_drafts: WhatsApp send failed user=%s", user_id[:8]
            )

    return delivered
