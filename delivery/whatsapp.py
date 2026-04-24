"""WhatsApp Cloud API channel implementation.

Renders OutboundMessage objects into WA API payloads and POSTs them.

WA constraints encoded here (not in message types):
  - Button titles truncated to 20 chars
  - CTAMessage with >3 buttons auto-degrades to ListMessage (single section)
  - List rows truncated to 24 chars (WA limit for row title)
  - Typing indicator: mark_as_read with typing_on (WA Cloud API ~2025)
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from config import settings
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

logger = logging.getLogger(__name__)

_WA_BASE = "https://graph.facebook.com/v19.0"
_BUTTON_TITLE_MAX = 20
_LIST_ROW_TITLE_MAX = 24


# ── Channel capabilities (consumed by act/compose prompts) ───────────────────

CAPABILITIES_PROMPT = """\
# HOW YOU USE WHATSAPP

Text is default. Every other widget is used only when it lands better than text would — less friction for the user to act, more legible, more calibrated. The best turn is usually one item. Max 3 non-delay items per turn.

- text: default. raw URLs auto-linkify.

- cta: text + 1-3 reply buttons. only for closed binary/trinary choices that save the user typing (yes/no, confirm/cancel). never for open questions. ids stay short and machine-readable. titles auto-truncate at 20 chars.

- cta_url: text + one tap-to-open button. for OAuth, external links, forms, dashboards — anything where the tap navigates away rather than returning a reply. label auto-truncates at 20 chars.

- list: text + scrollable options (up to 10 rows, grouped into sections). only when there are 4+ parallel choices the user will scan. rare. row titles auto-truncate at 24 chars.

- image: send a picture. requires a publicly accessible url from the provided "Available media" section — never invent one. use proactively when the answer is shape not words: a receipt the user shared, a chart of their week, a visual that makes the point faster than a paragraph would.

- document: file delivery (pdf, sheet, etc). requires url + filename. use when the user will save or forward it.

- voice_response: marks your reply for audio delivery — you provide no url, donna generates it. add {"type": "voice_response"} as the first item when the user sent a voice message, when the content is personal/emotional/conversational, or for step-by-step instructions easier to follow by ear. never for factual lists, links, or tables. cannot combine with cta / list / image / document.

- delay: a beat before the next item (0.5-4s). only when pacing genuinely helps — an ack before advice, a greeting before a question. never first or last.

- reply-to: any item can include "reply_to_message_id" to quote-reply a specific prior message. use when the thread has moved on and you're pulling something earlier back into focus.

widgets are not decoration. pick the one that makes the next user action cheapest. when in doubt, plain text wins."""


class WhatsAppChannel:
    """Sends OutboundMessage objects via WhatsApp Cloud API."""

    def __init__(self) -> None:
        self._phone_number_id = settings.whatsapp_phone_number_id
        self._token = settings.whatsapp_token

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    @property
    def _messages_url(self) -> str:
        return f"{_WA_BASE}/{self._phone_number_id}/messages"

    # ── Public interface ───────────────────────────────────────────────────────

    async def send(self, phone: str, message: OutboundMessage) -> str | None:
        payload = self._render(phone, message)
        data = await self._post(payload)
        try:
            messages = data.get("messages") or []
            if messages:
                return messages[0].get("id")
        except Exception:
            return None
        return None

    async def send_many(self, phone: str, messages: list) -> list[str]:
        """Send messages sequentially — WA doesn't guarantee order on concurrent sends.

        Supports Delay marker objects in the list to pause between messages.
        """
        wamids: list[str] = []
        for message in messages:
            if isinstance(message, Delay):
                await asyncio.sleep(message.seconds)
                continue
            wamid = await self.send(phone, message)
            if wamid:
                wamids.append(wamid)
        return wamids

    async def send_typing(self, phone: str, message_id: str | None = None) -> None:
        """Show typing indicator. Requires message_id to mark the incoming message as read.
        No-op (silent warning) if message_id is not provided."""
        if not message_id:
            logger.warning("send_typing: message_id required — skipping")
            return
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }
        try:
            await self._post(payload)
        except Exception:
            logger.warning("send_typing failed for %s — non-fatal", phone)

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render(self, phone: str, message: OutboundMessage) -> dict:
        base = {"messaging_product": "whatsapp", "to": phone}

        # Quote-reply context — attach to any message type
        reply_id = getattr(message, "reply_to_message_id", None)
        if reply_id:
            base["context"] = {"message_id": reply_id}

        if isinstance(message, TextMessage):
            return {**base, "type": "text", "text": {"body": message.body}}

        if isinstance(message, CTAMessage):
            if len(message.buttons) > 3:
                degraded = ListMessage(
                    body=message.body,
                    button_label="Choose one",
                    sections=[Section(title="Options", rows=message.buttons)],
                )
                return self._render(phone, degraded)
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": message.body},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": btn.id,
                                    "title": btn.title[:_BUTTON_TITLE_MAX],
                                },
                            }
                            for btn in message.buttons
                        ]
                    },
                },
            }

        if isinstance(message, CTAUrlMessage):
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": message.body},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": message.display_text[:_BUTTON_TITLE_MAX],
                            "url": message.url,
                        },
                    },
                },
            }

        if isinstance(message, ListMessage):
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": message.body},
                    "action": {
                        "button": message.button_label[:_BUTTON_TITLE_MAX],
                        "sections": [
                            {
                                "title": section.title,
                                "rows": [
                                    {
                                        "id": row.id,
                                        "title": row.title[:_LIST_ROW_TITLE_MAX],
                                    }
                                    for row in section.rows
                                ],
                            }
                            for section in message.sections
                        ],
                    },
                },
            }

        if isinstance(message, ImageMessage):
            image: dict = {"link": message.url}
            if message.caption:
                image["caption"] = message.caption
            return {**base, "type": "image", "image": image}

        if isinstance(message, AudioMessage):
            return {**base, "type": "audio", "audio": {"link": message.url}}

        if isinstance(message, DocumentMessage):
            doc: dict = {"link": message.url, "filename": message.filename}
            if message.caption:
                doc["caption"] = message.caption
            return {**base, "type": "document", "document": doc}

        raise TypeError(f"Unhandled message type: {type(message)}")

    # ── HTTP ───────────────────────────────────────────────────────────────────

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self._messages_url, headers=self._headers, json=payload
            )
            if resp.status_code >= 400:
                logger.error(
                    "WhatsApp API error %s: %s", resp.status_code, resp.text[:200]
                )
                resp.raise_for_status()
            return resp.json()
