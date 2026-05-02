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

Text is default. Use another widget only when it makes the next action cheaper or the answer clearer. The best turn is usually one item. Max 3 non-delay items per turn.

- text: default. raw urls auto-linkify.

- cta: text plus 1-3 reply buttons. only for closed choices like yes/no/confirm/cancel. never for open questions.

- cta_url: text plus one tap-to-open button. for oauth, external links, forms, dashboards, or anything that navigates away.

- list: scrollable options. only when there are 4+ parallel choices the user will scan. rare.

- image: use when the answer is visual. requires a publicly accessible url from available media. never invent one.

- document: file delivery. requires url and filename. use when the user will save or forward it.

- voice_response: this is the ONLY way to deliver a voice note. include it as an item in the send_burst messages array (place it first), with one or more text items after it. the text bodies are concatenated and synthesized as a single whatsapp voice note. saying "here is a voice message" in text without the voice_response item sends a text bubble, not voice. voice is RARE — text is the default reply mode in every turn, including when the inbound was a voice note (the user dictated for their own convenience, that is not a request for voice back). use voice_response only when (a) the user explicitly asks for it ("send me a voice", "voice me", "say it out loud"), or (b) the reply is personal and emotionally weighted in a way text would flatten — a pep talk, a soft check-in at a hard moment, a longform reflective reply. do not use for factual lists, links, tables, anything the user will scan visually, or short operational replies. cannot combine with cta, cta_url, list, image, or document. on any synthesis failure the burst falls back to text automatically.

- delay: a 0.5-4s beat before the next item. only when pacing helps. never first or last.

- reply-to: use reply_to_message_id when pulling an earlier message back into focus.

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

    @property
    def _media_url(self) -> str:
        return f"{_WA_BASE}/{self._phone_number_id}/media"

    # ── Public interface ───────────────────────────────────────────────────────

    async def upload_media(
        self, file_bytes: bytes, mime_type: str = "image/png"
    ) -> str:
        """Upload bytes to WA /media, return the media_id.

        Use this before sending an ImageMessage/AudioMessage/DocumentMessage
        with `media_id=...` set. Meta retains the media for 30 days.
        """
        files = {"file": ("upload.bin", file_bytes, mime_type)}
        data = {"messaging_product": "whatsapp", "type": mime_type}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self._media_url, headers=self._headers, data=data, files=files
            )
            if resp.status_code >= 400:
                logger.error(
                    "WhatsApp /media upload error %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.raise_for_status()
            body = resp.json()
        media_id = body.get("id")
        if not media_id:
            raise RuntimeError(
                f"WhatsApp /media response missing id: {body!r}"
            )
        return str(media_id)


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

    async def send_reaction(
        self, phone: str, message_id: str | None, emoji: str
    ) -> None:
        """React to an inbound message with an emoji. Fail-soft.

        Used as a lightweight ack on user-facing actions that take seconds
        (image generation, etc.) so the user sees something happen on their
        message immediately. No-op if message_id is missing.
        """
        if not message_id or not emoji:
            return
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "reaction",
            "reaction": {"message_id": message_id, "emoji": emoji},
        }
        try:
            await self._post(payload)
        except Exception:
            logger.warning("send_reaction failed for %s — non-fatal", phone[:6])

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
            image: dict = {"id": message.media_id} if message.media_id else {"link": message.url}
            if message.caption:
                image["caption"] = message.caption
            return {**base, "type": "image", "image": image}

        if isinstance(message, AudioMessage):
            audio: dict = (
                {"id": message.media_id} if message.media_id else {"link": message.url}
            )
            if message.voice:
                audio["voice"] = True
            return {**base, "type": "audio", "audio": audio}

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
