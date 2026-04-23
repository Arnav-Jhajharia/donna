"""Persist inbound + outbound messages for the turn (spec §6).

Runs first so downstream hooks can assume chat history is durable.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


async def run(ctx: Mapping[str, Any]) -> None:
    user_id = ctx.get("user_id")
    inbound = (ctx.get("inbound") or "").strip()
    outbound = list(ctx.get("outbound") or [])
    if not user_id:
        return
    if ctx.get("chat_already_persisted"):
        return

    from sqlalchemy import insert

    from backend.db.models import ChatMessage
    from backend.db.session import async_session

    rows: list[dict[str, Any]] = []
    if inbound:
        rows.append({"user_id": user_id, "role": "user", "content": inbound})
    for msg in outbound:
        text = (msg or "").strip()
        if text:
            rows.append({"user_id": user_id, "role": "assistant", "content": text})
    if not rows:
        return

    try:
        async with async_session() as session:
            await session.execute(insert(ChatMessage), rows)
            await session.commit()
    except Exception:
        logger.exception("save_chat_messages: persist failed")
