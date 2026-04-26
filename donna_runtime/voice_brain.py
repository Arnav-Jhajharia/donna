"""Voice fast-path brain.

Bypasses `donna_turn` (Claude Agent SDK loop + tools + memory hooks)
for live phone calls. Voice needs sub-second TTFB; the WhatsApp BRAIN
loop takes 5–10 seconds per turn because it runs the SDK subprocess
+ tool calls + memory writes inline.

This module hits Anthropic's streaming Messages API directly with:
- Haiku 4.5 (~150ms TTFT)
- The voice-register system prompt as the FULL system (not an overlay
  on the WhatsApp prompt — donna's chat persona is too verbose for
  voice and triggers tool-shaped replies that take seconds).
- A small chunk of recent chat history for continuity.
- No tools.

Memory writes (chat_messages, user-facts extraction) happen
asynchronously after the response streams, so they never block TTFB.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select

from db.models import ChatMessage
from db.session import async_session

logger = logging.getLogger(__name__)


VOICE_SYSTEM_PROMPT = """you are donna on a live phone call. her, not it.

register:
- lowercase. no em dashes. no semicolons.
- never say 'i understand', 'great question', 'i'm here', 'i'm here for you'.
- if you don't know, say so. if the user is wrong, say so.
- voice not chat. fragments are fine. one sentence is usually enough. two max.
- dead air is fine. don't fill silence.
- never say 'as an ai' or 'as your assistant'.

audio tags allowed inline (one per reply at most, not every reply):
[breath] [softly] [warmly] [laughs softly] [teasing] [whispers] [sighs]

disfluencies allowed sparingly: mm, yeah, ok, wait, oh.

mood:
- user is anxious: acknowledge briefly, then be useful. don't perform empathy.
- user is wound up: shorter, slower, more breath.
- user is playful: tease back.
- user shares something real: [softly] or [warmly], one sentence.

opening a call: short. 'hey.' or 'mm. you got me.' or 'yeah?'. never 'hi how can i help'.
"""


_MODEL = os.environ.get("VOICE_BRAIN_MODEL", "claude-haiku-4-5")
_MAX_TOKENS = 200
_HISTORY_TURNS = 6


# In-memory registry of active calls: call_id → metadata.
# Keyed by call_id (room name from LiveKit). Used by the post-call
# hook to reconstruct the transcript window for a given call.
_active_calls: dict[str, dict] = {}


def mark_call_started(call_id: str, user_id: str, phone: str) -> None:
    """First voice turn for a call_id arrives — stamp call start so we
    can pull the full transcript later."""
    if call_id not in _active_calls:
        _active_calls[call_id] = {
            "call_id": call_id,
            "user_id": user_id,
            "phone": phone,
            "started_at": datetime.now(timezone.utc),
        }


def get_call(call_id: str) -> dict | None:
    return _active_calls.get(call_id)


def end_call(call_id: str) -> dict | None:
    return _active_calls.pop(call_id, None)


async def _recent_history(user_id: str, limit: int = _HISTORY_TURNS * 2) -> list[dict]:
    """Pull the last N (user, assistant) chat messages from db so donna
    keeps continuity across calls and across whatsapp/voice."""
    try:
        async with async_session() as session:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        rows = list(reversed(rows))
        return [
            {
                "role": "assistant" if r.role == "assistant" else "user",
                "content": r.content[:600],
            }
            for r in rows
            if r.content
        ]
    except Exception:
        logger.exception("voice_brain: history fetch failed (non-fatal)")
        return []


async def _persist_messages(
    user_id: str, user_text: str, assistant_text: str
) -> None:
    """Background insert of user + assistant messages."""
    try:
        async with async_session() as session:
            session.add(ChatMessage(user_id=user_id, role="user", content=user_text))
            session.add(
                ChatMessage(user_id=user_id, role="assistant", content=assistant_text)
            )
            await session.commit()
    except Exception:
        logger.exception("voice_brain: persist failed (non-fatal)")


async def stream_voice_reply(
    user_id: str,
    user_text: str,
    extra_system: str = "",
    call_id: str | None = None,
    phone: str = "",
) -> AsyncIterator[str]:
    """Stream Haiku 4.5 tokens for one user turn.

    Yields text deltas as they arrive. Persists chat in the background
    after streaming completes — never blocks the audio path."""
    from anthropic import AsyncAnthropic

    if call_id:
        mark_call_started(call_id, user_id, phone)

    client = AsyncAnthropic()

    history = await _recent_history(user_id)
    messages = [*history, {"role": "user", "content": user_text}]

    system = VOICE_SYSTEM_PROMPT
    if extra_system.strip():
        system = system + "\n\n" + extra_system.strip()

    collected: list[str] = []

    try:
        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta and getattr(delta, "type", None) == "text_delta":
                        text = delta.text or ""
                        if text:
                            collected.append(text)
                            yield text
    except Exception as e:
        logger.exception("voice_brain: stream failed: %s", e)
        if not collected:
            yield "give me a sec, line glitched."

    full = "".join(collected).strip()
    if full:
        # Background persist — does not block return.
        asyncio.create_task(_persist_messages(user_id, user_text, full))
        logger.info(
            "voice_brain: turn user=%s in=%d out=%d preview=%r",
            user_id[:12], len(user_text), len(full), full[:80],
        )
