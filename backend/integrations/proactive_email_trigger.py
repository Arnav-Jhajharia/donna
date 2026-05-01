"""Single-source proactive trigger: 'important email arrived'.

When a Gmail webhook ingests a row, fan out here. Score → unified proactive
dispatcher → in mirror mode also invoke the legacy ``donna_turn`` proactive
flow so behavior does not change.

When ``DONNA_PROACTIVE_TIERED=1`` the dispatcher takes over: it ships
Tier 2 drafts directly, holds notes, drops with telemetry, and only
escalates to ``donna_turn`` when Tier 2 needs tools or fails.
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
from db.models import OpenLoop, User
from proactive.dispatcher import dispatch as dispatcher_dispatch
from proactive.dispatcher import is_tiered_active
from proactive.sources.email import (
    fetch_recent_sent_thread_ids,
    make_event,
)

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

    biography = (
        (user.living_profile or {}).get("biography", {})
        if user else {}
    )
    relationships = list(biography.get("relationships") or [])
    recent_sent = await fetch_recent_sent_thread_ids(user_id)
    return ScoringContext(
        biography_relationships=relationships,
        open_loop_keywords=[
            (loop.content or "").strip()
            for loop in loops if (loop.content or "").strip()
        ],
        recent_sent_thread_ids=recent_sent,
    )


def _format_trigger_prompt(msg: NormalizedGmailMessage, signals: list[str]) -> str:
    """DEPRECATED: only the legacy mirror-mode fallback path uses this.

    The unified dispatcher builds its own escalation prompt in
    ``proactive.dispatcher._build_escalation_prompt`` from the
    ``ProactiveEvent`` envelope. Kept here so mirror mode (Phase 1)
    remains a strict superset of pre-dispatcher behavior. Once mirror
    mode is fully retired, delete this and the legacy brain-path caller.
    """
    body_excerpt = (msg.body_text or msg.snippet or "")[:600]
    return (
        "[SYSTEM TRIGGER: proactive_email]\n"
        "A new email arrived that may be worth surfacing to the user. "
        "Decide whether to ping them. If the email is not actually "
        "surface-worthy on a second look, SKIP THIS FIRE: do not call "
        "send_burst, just end the turn. NEVER substitute a generic "
        "check-in like 'what's on your mind' or 'hey' — silence is "
        "correct when the email does not warrant a ping.\n\n"
        f"From: {msg.from_name or ''} <{msg.from_address}>\n"
        f"Subject: {msg.subject or ''}\n"
        f"Importance signals: {', '.join(signals) or 'none'}\n\n"
        f"{body_excerpt}"
    )


async def _invoke_brain(state: dict, config=None) -> dict:
    """Pluggable for tests. In prod, calls donna_runtime.brain.donna_turn."""
    from donna_runtime.brain import donna_turn

    return await donna_turn(state, config)


async def _run_legacy_brain_path(
    user_id: str, msg: NormalizedGmailMessage, score
) -> None:
    """Original score → arbiter → brain proactive turn flow.

    Kept verbatim so mirror mode (Phase 1) is a strict superset of
    today's behavior. When ``DONNA_PROACTIVE_TIERED=1`` the dispatcher
    handles ship/hold/drop/escalate and this path is skipped.
    """
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

    # Workers don't share filesystem with the API container, so SDK session
    # resume across services is impossible — see firing.py:fire_attention_via_brain.
    cfg = DonnaAgentConfig(mode="proactive", user_id=user_id, stateless_sessions=True)
    prompt = _format_trigger_prompt(msg, score.signals)
    state = {
        "user_id": user_id,
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


async def maybe_surface_email(
    user_id: str, msg: NormalizedGmailMessage
) -> None:
    """Phase 1/2 entry point.

    Phase 1 (default): the dispatcher runs in mirror mode (telemetry only)
    AND the legacy brain path runs. Phase 2 (``DONNA_PROACTIVE_TIERED=1``):
    only the dispatcher runs; legacy brain path is skipped unless the
    dispatcher itself escalates.
    """
    ctx = await _build_scoring_context(user_id)
    score = score_email(msg, ctx)
    if score.score < THRESHOLD:
        return

    event = make_event(user_id, msg, score)
    tiered = is_tiered_active()
    try:
        outcome = await dispatcher_dispatch(event)
    except Exception:
        logger.exception(
            "proactive_email: dispatcher raised user=%s msg=%s",
            user_id, msg.gmail_message_id,
        )
        outcome = None

    if tiered:
        # In gated mode the dispatcher owns the full path. The legacy
        # flow runs only when the dispatcher itself failed before
        # escalating (defensive — should be rare).
        if outcome is None:
            await _run_legacy_brain_path(user_id, msg, score)
        return

    # Mirror mode: run the legacy brain path regardless of dispatcher
    # outcome so existing behavior is unchanged.
    await _run_legacy_brain_path(user_id, msg, score)
