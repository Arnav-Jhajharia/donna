from __future__ import annotations

import json
import logging
from typing import Any

from ..hooks import _CURRENT_USER_ID
from ..tool_logic import text_content

logger = logging.getLogger(__name__)


def disabled_tool(*args, **kwargs):
    """Stub decorator that keeps the function importable without registering it as an SDK tool."""
    def decorator(f):
        return f
    return decorator


def _current_user_id() -> str | None:
    return _CURRENT_USER_ID.get()


def _tool_text(
    result: dict[str, Any],
    *,
    no_hits_text: str = "No hits.",
    degraded_text: str = "Memory unavailable.",
    voice_degraded: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """Render a ToolResult into chat content.

    When ``voice_degraded`` is True, the payload's `reason` is treated as
    the user-facing line (already Donna-voice) and forwarded verbatim.
    The ``degraded_text`` only applies when the reason is missing — i.e.
    a code path that returned `degraded()` without a message.
    """
    status = result.get("status")
    payload = result.get("payload")
    if status == "degraded":
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if voice_degraded and reason:
            return text_content(reason)
        return text_content(f"{degraded_text}{f' {reason}' if reason else ''}")
    if status == "no_hits" or not payload:
        return text_content(no_hits_text)
    return text_content(_render_payload(payload))


_LIST_CAP = 10


def _render_payload(payload: Any, *, narrow_hint: str | None = None) -> str:
    if isinstance(payload, list):
        total = len(payload)
        lines: list[str] = []
        for item in payload[:_LIST_CAP]:
            if isinstance(item, dict):
                lines.append("- " + _render_dict_item(item))
            else:
                lines.append(f"- {item}")
        rendered = "\n".join(lines)
        if total > _LIST_CAP:
            hint = narrow_hint or "narrow with a more specific query, period, or purpose"
            rendered += f"\n(showing {_LIST_CAP} of {total} — {hint})"
        return rendered
    if isinstance(payload, dict):
        return json.dumps(payload, default=str, sort_keys=True)
    return str(payload)


def _render_dict_item(item: dict[str, Any]) -> str:
    for key in ("content", "fact", "rule", "title"):
        if item.get(key):
            prefix = f"{item.get('source')}: " if item.get("source") else ""
            return prefix + str(item[key])
    return json.dumps(item, default=str, sort_keys=True)


def _result_text(
    label: str,
    result: dict[str, Any],
    *,
    no_hits_text: str | None = None,
    degraded_text: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    status = result.get("status")
    payload = result.get("payload")
    if status == "ok":
        return text_content(f"{label}: {_render_payload(payload)}")
    if status == "no_hits":
        return text_content(no_hits_text or f"{label}: no hits.")
    reason = payload.get("reason") if isinstance(payload, dict) else None
    suffix = f" {reason}" if reason else ""
    return text_content((degraded_text or f"{label}: unavailable.") + suffix)
