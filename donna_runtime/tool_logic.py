from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from .hooks import _CURRENT_USER_ID, _OUTBOUND_BUFFER

logger = logging.getLogger(__name__)


def text_content(text: str) -> dict[str, list[dict[str, str]]]:
    return {"content": [{"type": "text", "text": text}]}


def send_burst_text(messages: Sequence[str]) -> str:
    return f"Sent {len(messages)} messages."


def stay_silent_text() -> str:
    return "Silence logged."


def _current_user_id() -> str | None:
    return _CURRENT_USER_ID.get()


def _render_episodic_hits(payload: Any, limit: int) -> str:
    if not payload:
        return "No matching memories found."
    lines: list[str] = []
    for item in payload[:limit]:
        if isinstance(item, dict):
            content = item.get("content") or item.get("summary") or item.get("text") or ""
            ts = item.get("created_at") or item.get("timestamp") or ""
            lines.append(f"[{ts}] {content}".strip())
        else:
            lines.append(str(item))
    return "\n".join(l for l in lines if l) or "No matching memories found."


async def recall_episodic_result(args: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    from backend.memory.tools.recall_episodic import recall_episodic

    user_id = _current_user_id()
    query = str(args.get("query", "")).strip()
    if not user_id or not query:
        return text_content("No matching memories found.")
    try:
        res = await recall_episodic(user_id=user_id, query=query, limit=5)
    except Exception:
        logger.exception("recall_episodic_result failed")
        return text_content("Memory unavailable.")
    if res.get("status") == "degraded":
        return text_content("Memory unavailable.")
    return text_content(_render_episodic_hits(res.get("payload"), limit=5))


async def read_tracker_result(args: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    from backend.memory.tools.list_observations import list_observations

    user_id = _current_user_id()
    name = str(args.get("name", "")).strip()
    if not user_id or not name:
        return text_content(f"No tracker named '{name}'.")
    try:
        res = await list_observations(user_id=user_id, type=name, limit=20)
    except Exception:
        logger.exception("read_tracker_result failed")
        return text_content("Tracker unavailable.")
    payload = res.get("payload") or []
    if res.get("status") in ("no_hits", "degraded") or not payload:
        return text_content(f"No tracker named '{name}'.")
    return text_content(json.dumps(payload[:5], default=str))


async def send_burst_result(args: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    from delivery.messages import TextMessage

    raw_messages = args.get("messages", ())
    messages = raw_messages if isinstance(raw_messages, Sequence) and not isinstance(raw_messages, str) else ()
    buffer = _OUTBOUND_BUFFER.get()
    if buffer is not None:
        for m in messages:
            body = m if isinstance(m, str) else str(m)
            if body:
                buffer.append(TextMessage(body=body))
    return text_content(send_burst_text(messages))


async def stay_silent_result(args: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    return text_content(stay_silent_text())
