from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from delivery.messages import (
    AudioMessage,
    Button,
    CTAMessage,
    CTAUrlMessage,
    Delay,
    DocumentMessage,
    ImageMessage,
    ListMessage,
    OutboundMessage,
    Section,
    TextMessage,
)

from .hooks import _CURRENT_USER_ID, _OUTBOUND_BUFFER
from .voice_filter import filter_burst_items

logger = logging.getLogger(__name__)

_VOICE_FILTER_ENABLED: bool = True


def set_voice_filter_enabled(enabled: bool) -> None:
    """Toggle the voice filter. Runner sets this from DonnaAgentConfig."""
    global _VOICE_FILTER_ENABLED
    _VOICE_FILTER_ENABLED = bool(enabled)


def text_content(text: str) -> dict[str, list[dict[str, str]]]:
    return {"content": [{"type": "text", "text": text}]}


def send_burst_text(messages: Sequence[Any]) -> str:
    real = [m for m in messages if not isinstance(m, Delay)]
    return f"Sent {len(real)} messages."


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
        period = str(args.get("period") or "").strip() or None
        res = await list_observations(user_id=user_id, type=name, period=period, limit=20)
    except Exception:
        logger.exception("read_tracker_result failed")
        return text_content("Tracker unavailable.")
    payload = res.get("payload") or []
    if res.get("status") in ("no_hits", "degraded") or not payload:
        return text_content(f"No tracker named '{name}'.")
    return text_content(json.dumps(payload[:5], default=str))


# ── send_burst (terminator) ──────────────────────────────────────────────────


def _build_outbound(item: Any) -> OutboundMessage | Delay | None:
    """Construct an OutboundMessage from one schema item.

    Schema shape: discriminated union on `type`. Returns None for items the
    schema validator should have rejected (defensive, not authoritative).
    Bare strings are accepted as plain text for back-compat with tests.
    """
    if isinstance(item, str):
        body = item.strip()
        return TextMessage(body=body) if body else None

    if not isinstance(item, Mapping):
        return None

    item_type = str(item.get("type", "")).lower()
    reply_to = item.get("reply_to_message_id") or None

    if item_type == "text":
        body = str(item.get("body", "")).strip()
        if not body:
            return None
        return TextMessage(body=body, reply_to_message_id=reply_to)

    if item_type == "cta":
        body = str(item.get("body", "")).strip()
        raw_buttons = item.get("buttons")
        if not body or not isinstance(raw_buttons, Sequence) or isinstance(raw_buttons, str):
            return None
        buttons = [
            Button(id=str(b.get("id", "")), title=str(b.get("title", "")))
            for b in raw_buttons
            if isinstance(b, Mapping) and b.get("id") and b.get("title")
        ]
        if not buttons:
            return None
        return CTAMessage(body=body, buttons=buttons, reply_to_message_id=reply_to)

    if item_type == "cta_url":
        body = str(item.get("body", "")).strip()
        url = str(item.get("url", "")).strip()
        display_text = str(item.get("display_text", "")).strip()
        if not (body and url and display_text):
            return None
        return CTAUrlMessage(
            body=body,
            display_text=display_text,
            url=url,
            reply_to_message_id=reply_to,
        )

    if item_type == "list":
        body = str(item.get("body", "")).strip()
        button_label = str(item.get("button_label", "")).strip()
        raw_sections = item.get("sections")
        if not (body and button_label) or not isinstance(raw_sections, Sequence) or isinstance(raw_sections, str):
            return None
        sections: list[Section] = []
        for sec in raw_sections:
            if not isinstance(sec, Mapping):
                continue
            raw_rows = sec.get("rows")
            if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, str):
                continue
            rows = [
                Button(id=str(r.get("id", "")), title=str(r.get("title", "")))
                for r in raw_rows
                if isinstance(r, Mapping) and r.get("id") and r.get("title")
            ]
            if rows:
                sections.append(Section(title=str(sec.get("title", "")), rows=rows))
        if not sections:
            return None
        return ListMessage(body=body, button_label=button_label, sections=sections)

    if item_type == "image":
        url = str(item.get("url", "")).strip()
        if not url:
            return None
        caption = str(item.get("caption", "")).strip()
        return ImageMessage(url=url, caption=caption, reply_to_message_id=reply_to)

    if item_type == "delay":
        try:
            seconds = float(item.get("seconds"))
        except (TypeError, ValueError):
            return None
        # Schema enforces 0.5–4.0; clamp defensively.
        return Delay(seconds=max(0.0, min(seconds, 10.0)))

    return None


def render_outbound_text(message: Any) -> str | None:
    """Best-effort plain-text representation of a constructed OutboundMessage.

    Used for chat_messages persistence so quote-reply context survives across
    turns even when Donna sent a CTA / list / image. Returns None to skip
    persistence (delays, voice markers, anything unrenderable).
    """
    if isinstance(message, Delay):
        return None
    if isinstance(message, TextMessage):
        return message.body or None
    if isinstance(message, CTAMessage):
        labels = " | ".join(b.title for b in message.buttons)
        return f"{message.body}\n[buttons: {labels}]" if labels else message.body
    if isinstance(message, CTAUrlMessage):
        return f"{message.body}\n[{message.display_text}: {message.url}]"
    if isinstance(message, ListMessage):
        labels = " | ".join(r.title for sec in message.sections for r in sec.rows)
        return f"{message.body}\n[options: {labels}]" if labels else message.body
    if isinstance(message, ImageMessage):
        return f"[image: {message.url}] {message.caption}".strip() if message.caption else f"[image: {message.url}]"
    if isinstance(message, AudioMessage):
        return f"[audio: {message.url}]"
    if isinstance(message, DocumentMessage):
        return f"[doc: {message.filename}] {message.caption}".strip() if message.caption else f"[doc: {message.filename}]"
    return None


def render_burst_items_text(items: Any) -> list[str]:
    """Render raw schema items (the form `send_burst` receives in `args`)
    into plain text strings for memory hooks. Drops delays."""
    if not isinstance(items, Sequence) or isinstance(items, str):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
            continue
        if not isinstance(item, Mapping):
            continue
        t = str(item.get("type", "")).lower()
        if t in ("delay", ""):
            continue
        body = str(item.get("body", "")).strip()
        if t == "text":
            if body:
                out.append(body)
        elif t == "cta":
            titles = [
                str(b.get("title", ""))
                for b in (item.get("buttons") or [])
                if isinstance(b, Mapping)
            ]
            out.append(f"{body} [buttons: {' | '.join(titles)}]" if titles else body)
        elif t == "cta_url":
            out.append(f"{body} [{item.get('display_text', '')}: {item.get('url', '')}]")
        elif t == "list":
            out.append(body)
        elif t == "image":
            cap = str(item.get("caption", "")).strip()
            out.append(f"[image] {cap}" if cap else "[image]")
    return out


async def send_burst_result(args: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw_messages = args.get("messages", ())
    items = (
        raw_messages
        if isinstance(raw_messages, Sequence) and not isinstance(raw_messages, str)
        else ()
    )

    if _VOICE_FILTER_ENABLED and items:
        filtered_items, violations = filter_burst_items(items)
        if violations:
            logger.warning("voice_filter violations=%s", list(violations))
        items = filtered_items

    constructed: list[OutboundMessage | Delay] = []
    for item in items:
        msg = _build_outbound(item)
        if msg is not None:
            constructed.append(msg)

    buffer = _OUTBOUND_BUFFER.get()
    if buffer is not None:
        buffer.extend(constructed)
    return text_content(send_burst_text(constructed))
