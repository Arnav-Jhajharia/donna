"""Thin replacement for the old LangGraph entry.

Exports:
  state_from_payload(payload) -> dict
  user_lookup(state) -> dict     (returns the augmented state)

The LangGraph orchestration is gone. api/main.py calls these directly,
then hands the state to donna_runtime.brain.donna_turn.
"""
from __future__ import annotations

import logging
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from db.models import ChatMessage, User
from db.session import async_session
from ingress.payload import IngressPayload

logger = logging.getLogger(__name__)


# Rough country-code → tz guesser. Falls back to Singapore.
_TZ_BY_PREFIX: list[tuple[str, str]] = [
    ("+1", "America/Los_Angeles"),
    ("+44", "Europe/London"),
    ("+81", "Asia/Tokyo"),
    ("+91", "Asia/Kolkata"),
    ("+65", "Asia/Singapore"),
]


def phone_info(phone: str) -> tuple[str, str]:
    for prefix, tz in _TZ_BY_PREFIX:
        if phone.startswith(prefix):
            return tz, prefix
    return "Asia/Singapore", ""


def state_from_payload(payload: IngressPayload) -> dict:
    """Flat state dict consumed by user_lookup + ingress.node.enrich + brain.donna_turn."""
    return {
        "user_id": payload.user_id,
        "phone": payload.phone,
        "message_type": payload.message_type,
        "raw_input": payload.message or "",
        "_ingress_payload": payload,
        "platform_message_id": payload.platform_message_id,
        "platform_profile_name": payload.platform_profile_name,
        "reply_to_id": payload.reply_to_id,
        "reply_to_content": None,
        "reply_to_role": None,
        "_user_timezone": None,
        "_user_name": None,
        "_user_facts": None,
        "_is_first_message": None,
        "transcription": None,
        "image_bytes_b64": None,
        "image_mime_type": None,
        "document_received": None,
        "document_filename": None,
        "document_mime_type": None,
        "document_extracted_text": None,
        "document_public_url": None,
        "sm_doc_id": None,
        "url_contents": None,
        "recent_messages": None,
        "_outbound": None,
    }


async def user_lookup(state: dict) -> dict:
    """Resolve phone → user_id, creating user if not found. Returns the mutated state."""
    phone = state["phone"]
    profile_name = state.get("platform_profile_name") or ""
    is_first_message = False

    guessed_prefix = ""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if user is None:
            guessed_tz, guessed_prefix = phone_info(phone)
            user = User(
                id=str(uuid.uuid4()),
                phone=phone,
                name=profile_name or None,
                timezone=guessed_tz,
            )
            try:
                goals = dict(user.onboarding_goals or {})
                goals.setdefault("tz_done", False)
                goals.setdefault("watch_done", False)
                goals["tz_source"] = "phone_guess"
                if guessed_prefix:
                    goals["tz_guess_prefix"] = guessed_prefix
                user.onboarding_goals = goals
            except Exception:
                pass
            session.add(user)
            await session.commit()
            await session.refresh(user)
            is_first_message = True

    if not is_first_message:
        async with async_session() as session:
            count_result = await session.execute(
                select(func.count(ChatMessage.id))
                .where(ChatMessage.user_id == user.id, ChatMessage.role == "assistant")
            )
            is_first_message = (count_result.scalar() or 0) == 0

    goals = user.onboarding_goals if isinstance(getattr(user, "onboarding_goals", None), dict) else {}
    tz_done = bool(goals.get("tz_done")) if isinstance(goals, dict) else False
    tz_source = str(goals.get("tz_source") or ("phone_guess" if is_first_message else "")) if isinstance(goals, dict) else ""

    state.update({
        "user_id": user.id,
        "_user_timezone": user.timezone or "Asia/Singapore",
        "_user_name": user.name or profile_name or "",
        "_user_facts": dict(user.facts or {}),
        "_is_first_message": is_first_message,
        "_tz_done": tz_done,
        "_tz_source": tz_source,
        "_tz_guess_prefix": str(goals.get("tz_guess_prefix") or guessed_prefix or "") if isinstance(goals, dict) else "",
    })
    return state
