"""Unconditional Supermemory episode write (spec §6).

Every send_burst turn produces exactly one episode summarizing the turn.
Degrades silently when Supermemory is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from backend.memory.clients.supermemory import get_memory_client

logger = logging.getLogger(__name__)


def _format_episode(inbound: str, outbound: list[str]) -> str:
    parts: list[str] = []
    if inbound.strip():
        parts.append(f"USER: {inbound.strip()}")
    for msg in outbound:
        text = (msg or "").strip()
        if text:
            parts.append(f"DONNA: {text}")
    return "\n".join(parts)


async def run(ctx: Mapping[str, Any]) -> None:
    user_id = ctx.get("user_id")
    inbound = ctx.get("inbound") or ""
    outbound = list(ctx.get("outbound") or [])
    if not user_id:
        return

    body = _format_episode(inbound, outbound)
    if not body:
        return

    client = get_memory_client()
    if not client.available:
        return

    try:
        await client.add_episode(user_id=user_id, content=body)
    except Exception:
        logger.exception("record_episode: add_episode failed")
