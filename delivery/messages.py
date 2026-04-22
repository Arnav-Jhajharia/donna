"""Abstract outbound message types — what Act produces.

These are channel-agnostic. Each channel implementation (delivery/whatsapp.py,
future delivery/imessage.py, etc.) translates them into platform-specific
payloads. Act never imports from whatsapp.py directly — it produces these
abstract types, and the channel handles rendering and fallbacks.

Each channel also exports a CAPABILITIES_PROMPT describing what it supports,
which act's LLM prompts consume so compose knows what it can emit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass
class TextMessage:
    body: str
    reply_to_message_id: str | None = None   # platform message ID to quote-reply to


@dataclass
class Button:
    id: str      # payload echoed back when tapped — keep it short and machine-readable
    title: str   # display label — WA enforces max 20 chars, channel layer truncates


@dataclass
class CTAMessage:
    """Text with reply buttons. Tapping a button sends its title back as a
    text inbound. 1–3 buttons render as WA button message. More than 3
    auto-degrades to a list message in the WA renderer."""
    body: str
    buttons: list[Button]
    reply_to_message_id: str | None = None


@dataclass
class CTAUrlMessage:
    """Text with a single URL button. Tapping opens the URL in the user's
    browser. Use this for OAuth links, external sites, forms, dashboards —
    anything where the tap should navigate away rather than return a reply."""
    body: str
    display_text: str      # label on the button (e.g. "Connect", "Open Dashboard")
    url: str               # the URL to open when tapped
    reply_to_message_id: str | None = None


@dataclass
class Section:
    title: str
    rows: list[Button]


@dataclass
class ListMessage:
    """Scrollable list of options — WA supports up to 10 rows across sections."""
    body: str
    button_label: str   # text on the "open list" trigger button
    sections: list[Section]


@dataclass
class ImageMessage:
    url: str            # publicly accessible URL or WA media ID
    caption: str = ""
    reply_to_message_id: str | None = None


@dataclass
class AudioMessage:
    url: str            # publicly accessible URL or WA media ID
    reply_to_message_id: str | None = None


@dataclass
class DocumentMessage:
    url: str            # publicly accessible URL or WA media ID
    filename: str
    caption: str = ""
    reply_to_message_id: str | None = None


@dataclass
class Delay:
    """Marker in an outbound list — tells the delivery layer to pause before
    sending the next message. Used for natural conversational pacing."""
    seconds: float


@dataclass
class VoiceResponseMarker:
    """Sentinel emitted by compose when the LLM decides the reply should be
    delivered as audio. _maybe_tts in api/main.py detects this, runs TTS on
    the text items, and replaces the whole outbound with an AudioMessage."""


OutboundMessage = Union[
    TextMessage,
    CTAMessage,
    CTAUrlMessage,
    ListMessage,
    ImageMessage,
    AudioMessage,
    DocumentMessage,
]
