"""Surface → WhatsApp delivery glue.

Takes a ``SurfaceResult`` from a Surfacer and turns it into:
  - a ``ChatMessage`` row (audit trail, dashboard visibility)
  - a WhatsApp burst via ``delivery.whatsapp.WhatsAppChannel.send_many``

Modes:
  - ``shadow`` — persists the ChatMessage with is_shadow=True, no send
  - ``live``   — persists + sends

Per-user mode comes from ``User.living_profile.attention_delivery_mode``;
defaults to ``shadow`` for safety until calibration is done. The brain's
existing send_burst path is unaffected — this is a separate channel for
attention-runtime-driven bursts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select

from backend.memory.attention.runtime import SurfaceResult
from db.models import AttentionRow, ChatMessage, User
from db.session import async_session

logger = logging.getLogger(__name__)

DeliveryMode = Literal["shadow", "live"]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_FIRING_KINDS = {"escalation", "burst", "nudge"}


async def deliver_surface(
    *,
    user_id: str,
    attention_id: str,
    surface: SurfaceResult,
    mode: DeliveryMode | None = None,
) -> bool:
    """Deliver one surface result. Returns True if a message was sent.

    No-op when surface.kind is not a firing kind (silent / skip).
    No-op when surface.message is empty.
    """
    if surface.kind not in _FIRING_KINDS:
        return False
    body = (surface.message or "").strip()
    if not body:
        return False

    resolved_mode = mode or await _resolve_mode(user_id)

    # Persist the ChatMessage either way (audit + dashboard).
    message_id: str | None = None
    async with async_session() as session:
        row = ChatMessage(
            user_id=user_id,
            role="assistant",
            content=body,
            is_proactive=True,
            is_shadow=(resolved_mode == "shadow"),
            created_at=_utcnow_naive(),
        )
        session.add(row)
        await session.flush()
        message_id = row.id
        # Stamp the attention's last_surfaced_at so the dashboard /
        # the runtime can compute silent_for_seconds correctly.
        att_row = (
            await session.execute(
                select(AttentionRow).where(AttentionRow.id == attention_id)
            )
        ).scalar_one_or_none()
        if att_row is not None:
            att_row.last_surfaced_at = _utcnow_naive()
        await session.commit()

    try:
        from donna_runtime.observability import emit

        emit(
            "proactive.delivered",
            user_id=user_id,
            source="attention_runtime",
            surface="memory/attention/delivery",
            message_id=message_id,
            mode=resolved_mode,
            is_shadow=(resolved_mode == "shadow"),
            attention_id=attention_id,
            kind=surface.kind,
            draft_preview=(body or "")[:200],
        )
    except Exception:
        logger.exception(
            "deliver_surface: proactive.delivered emit failed user=%s attention=%s",
            user_id[:8],
            attention_id[:8],
        )

    if resolved_mode == "shadow":
        logger.info(
            "deliver_surface: shadow mode user=%s attention=%s kind=%s",
            user_id[:8],
            attention_id[:8],
            surface.kind,
        )
        return False

    # Live: send via WhatsApp.
    try:
        from delivery.whatsapp import WhatsAppChannel

        phone = await _user_phone(user_id)
        if not phone:
            logger.warning(
                "deliver_surface: live mode but user has no phone user=%s",
                user_id[:8],
            )
            return False
        channel = WhatsAppChannel()
        await channel.send_many(phone, [body])
        return True
    except Exception:
        logger.exception(
            "deliver_surface: WhatsApp send failed user=%s attention=%s",
            user_id[:8],
            attention_id[:8],
        )
        return False


async def _resolve_mode(user_id: str) -> DeliveryMode:
    """Read per-user delivery mode from living_profile, default to shadow."""
    try:
        async with async_session() as session:
            u = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if u is None:
                return "shadow"
            lp = u.living_profile or {}
            mode = (lp.get("attention_delivery_mode") or "shadow").lower()
            return "live" if mode == "live" else "shadow"
    except Exception:
        logger.exception(
            "deliver_surface: mode resolution failed user=%s", user_id[:8]
        )
        return "shadow"


async def _user_phone(user_id: str) -> str | None:
    async with async_session() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    return getattr(u, "phone", None) if u else None
