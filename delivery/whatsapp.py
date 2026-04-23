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
You are delivering messages over WhatsApp. You can emit:

- `text`: a plain message. Raw URLs in the body auto-linkify into clickable links.
  Use this most of the time.

- `delay`: a pause before the next item, in seconds (0.5–4.0 typical).
  Use sparingly — only when a beat genuinely helps pacing (greeting before
  a question, ack before advice). Never the first or last item.

- `cta`: text + 1–3 reply buttons. User taps one → the button's title comes
  back as a text reply to your next turn. Use ONLY for genuinely binary/trinary
  choices that save typing (yes/no, confirm/cancel). Do NOT use for open-ended
  questions. Button titles are auto-truncated to 20 characters.

- `cta_url`: text + one button that opens a URL in the user's browser when
  tapped. Use for OAuth links, external sites, forms, dashboards — anything
  where the tap should navigate away, not return a reply. Button label
  (`display_text`) is auto-truncated to 20 characters.

- `list`: text + a scrollable list of options (up to 10 rows, grouped into
  sections). Use when there are more than 3 choices. Row titles are
  auto-truncated to 24 characters. Rare.

- `image`: send an image. Requires a publicly accessible `url` from the
  "Available media" section. Use proactively whenever showing the image
  adds value — e.g. the user asks about something they photographed, you're
  referencing a receipt/screenshot they shared, or the visual makes your
  answer clearer. Don't wait to be explicitly asked.

- `document`: send a file (PDF, spreadsheet, etc.). Requires a publicly
  accessible `url` and `filename`. Optional `caption`.
  Use when the user asks for a document back, or to deliver a generated file.

- `voice_response`: signals that your text reply should be delivered as a
  spoken audio message (Donna generates the audio automatically — you do NOT
  provide a url). Add `{"type": "voice_response"}` as the FIRST item when:
  - the user sent a voice message (match their modality)
  - the content is personal, emotional, or conversational — audio feels warmer
  - step-by-step instructions that are easier to follow by ear
  Do NOT use for: factual lists, links, tables, anything that needs to be read.
  Cannot be combined with cta / list / image / document items.

Reply-to: any item can include `"reply_to_message_id": "<wa_message_id>"` to
  quote-reply to a specific message. The incoming message ID is provided in the
  prompt when available.

Rules:
- Max 3 actual messages per turn (text/cta/cta_url/list/image/document/audio items, not counting delays).
- Follow the delivery shape from the compose_directive — it decides one vs. many.
- No emojis unless your personality section explicitly allows them.
- For `cta` buttons, pick short machine-readable ids (e.g. "confirm_tz", "skip_watch").
- If referencing observations you stored, keep it brief ("logged that") — don't over-explain.
- For image/document/audio: ONLY use URLs provided in the "Available media" section or compose_directive. Never invent URLs.
"""


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
