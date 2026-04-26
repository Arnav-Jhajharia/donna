"""Post-call brain hook.

After a voice call ends, run the FULL BRAIN loop against the
transcript. Voice-fast-path (Haiku, no tools) handles the live
conversation; this hook catches up afterward to:

- Extract any commitments donna made during the call.
- Schedule reminders / actions she promised.
- Write user-facts the live brain noticed.
- Send a WhatsApp follow-up summary if anything is worth surfacing.

Triggered by api/voice_routes.py POST /voice/post-call, which is fired
by the LiveKit agent worker on session close.

Shape: the post-call brain receives the call transcript as the user's
"input" with a system overlay explaining the situation. Existing tools
(remember, schedule, send_burst, etc.) all work normally — donna's
brain decides what to do.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import ChatMessage
from db.session import async_session

from .brain import donna_turn
from .config import DonnaAgentConfig
from .voice_brain import end_call

logger = logging.getLogger(__name__)


POST_CALL_SYSTEM = """\
you just got off a phone call with the user. below is the transcript.

your job now:
1. note anything they said worth remembering (use `remember` tool).
2. if you committed to anything during the call (a reminder, a callback,
   research, a draft, a search), DO IT NOW. use the appropriate tool.
3. if anything is worth surfacing on whatsapp — a recap, a question
   that needs an answer, a confirmation of what you committed to —
   send it via send_burst. ONE short message. lowercase voice.
4. if nothing is worth surfacing on whatsapp, do not send anything.
   silence is allowed. dead air is fine.

do not just say "i'll do that" — actually invoke the tool. the user
already heard you say that on the call.
"""


async def _fetch_call_transcript(
    user_id: str, started_at: datetime, max_messages: int = 80
) -> list[ChatMessage]:
    """All chat_messages for this user since call started."""
    try:
        async with async_session() as session:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .where(ChatMessage.created_at >= started_at)
                .order_by(ChatMessage.created_at.asc())
                .limit(max_messages)
            )
            return list((await session.execute(stmt)).scalars().all())
    except Exception:
        logger.exception("post_call: transcript fetch failed")
        return []


def _format_transcript(rows: list[ChatMessage]) -> str:
    """Render rows as 'role: content' lines."""
    lines: list[str] = []
    for r in rows:
        speaker = "user" if r.role == "user" else "donna"
        body = (r.content or "").strip()
        if body:
            lines.append(f"{speaker}: {body}")
    return "\n".join(lines)


async def run_post_call(
    call_id: str,
    user_id: str,
    phone: str,
    started_at: datetime | None = None,
) -> dict:
    """Run the full brain over the call transcript. Returns a small
    summary so the caller can log the result."""

    call = end_call(call_id)
    started = started_at or (call or {}).get(
        "started_at", datetime.now(timezone.utc)
    )

    rows = await _fetch_call_transcript(user_id, started)
    if not rows:
        logger.info(
            "post_call: %s — no transcript rows, skipping brain", call_id[:12]
        )
        return {"ok": True, "skipped": True, "reason": "no transcript"}

    transcript = _format_transcript(rows)
    logger.info(
        "post_call: %s — running brain over %d turns (%d chars)",
        call_id[:12], len(rows), len(transcript),
    )

    state = {
        "raw_input": (
            "the call just ended. the transcript is between user and donna "
            "(you, before this turn). do the work.\n\n" + transcript
        ),
        "user_id": user_id,
        "phone": phone,
        "platform_message_id": f"post-call-{call_id}",
        "channel": "post_call",
    }
    cfg = DonnaAgentConfig(system_context=POST_CALL_SYSTEM)

    try:
        result = await donna_turn(state, cfg)
    except Exception:
        logger.exception("post_call: brain failure")
        return {"ok": False, "error": "brain failure"}

    outbound = result.get("_outbound") or []
    return {
        "ok": True,
        "call_id": call_id,
        "user_id": user_id,
        "transcript_chars": len(transcript),
        "outbound_count": len(outbound),
    }
