"""Single-source proactive trigger: 'important email arrived'.

When a Gmail webhook ingests a row, fan out here. Score → rate-limit →
invoke Donna's brain in mode='proactive' with the email as trigger context.

NOTE: this is one hardcoded producer. The general noticing layer (multi-
source, learning-aware) is a separate spec.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.email_importance import (
    ScoringContext,
    score_email,
)
from backend.integrations.proactive_rate_limit import (
    can_fire_proactive,
    record_ping,
)
from db.models import ChatMessage, OpenLoop, User

logger = logging.getLogger(__name__)

THRESHOLD = 0.5


def _session_factory():
    from backend.db.session import async_session

    return async_session


async def _build_scoring_context(user_id: str) -> ScoringContext:
    async with _session_factory()() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        loops = (
            await session.execute(
                select(OpenLoop)
                .where(OpenLoop.user_id == user_id)
                .where(OpenLoop.status == "active")
            )
        ).scalars().all()
        # Fetched but unused for now — sent-folder mirror not in P2.
        _recent_sent = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(50)
            )
        ).scalars().all()

    biography = (
        (user.living_profile or {}).get("biography", {})
        if user else {}
    )
    relationships = list(biography.get("relationships") or [])
    return ScoringContext(
        biography_relationships=relationships,
        open_loop_keywords=[
            (loop.content or "").strip()
            for loop in loops if (loop.content or "").strip()
        ],
        recent_sent_thread_ids=set(),
    )


def _format_trigger_prompt(msg: NormalizedGmailMessage, signals: list[str]) -> str:
    body_excerpt = (msg.body_text or msg.snippet or "")[:600]
    return (
        "[SYSTEM TRIGGER: proactive_email]\n"
        "A new email arrived that may be worth surfacing to the user. "
        "Decide whether to ping them. Use stay_silent if the email is not "
        "actually surface-worthy on a second look.\n\n"
        f"From: {msg.from_name or ''} <{msg.from_address}>\n"
        f"Subject: {msg.subject or ''}\n"
        f"Importance signals: {', '.join(signals) or 'none'}\n\n"
        f"{body_excerpt}"
    )


async def _invoke_brain(state: dict, config=None) -> dict:
    """Pluggable for tests. In prod, calls donna_runtime.brain.donna_turn."""
    from donna_runtime.brain import donna_turn

    return await donna_turn(state, config)


async def maybe_surface_email(
    user_id: str, msg: NormalizedGmailMessage
) -> None:
    ctx = await _build_scoring_context(user_id)
    score = score_email(msg, ctx)
    if score.score < THRESHOLD:
        return

    decision = await can_fire_proactive(user_id, source="email")
    if not decision.allowed:
        await record_ping(
            user_id,
            "email",
            msg.gmail_message_id,
            suppressed_reason=decision.reason,
        )
        logger.info(
            "proactive_email: suppressed user=%s reason=%s",
            user_id, decision.reason,
        )
        return

    from donna_runtime.config import DonnaAgentConfig

    cfg = DonnaAgentConfig(mode="proactive", user_id=user_id)
    prompt = _format_trigger_prompt(msg, score.signals)
    state = {
        "user_id": user_id,
        # raw_input is what brain.donna_turn reads; user_message is the
        # human-friendly mirror used for tracing + tests.
        "raw_input": prompt,
        "user_message": prompt,
        "trigger": {
            "source": "email",
            "message_ref": msg.gmail_message_id,
            "score": score.score,
            "signals": score.signals,
        },
    }
    try:
        await _invoke_brain(state, cfg)
        await record_ping(user_id, "email", msg.gmail_message_id)
    except Exception:
        logger.exception(
            "proactive_email: brain invocation failed user=%s msg=%s",
            user_id, msg.gmail_message_id,
        )
