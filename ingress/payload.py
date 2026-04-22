# ingress/payload.py
"""Transport-agnostic inbound payload.

Every platform adapter (WhatsApp, web, API, etc.) normalizes its raw webhook
data into an IngressPayload before handing it to the pipeline. The pipeline
never imports platform-specific code.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocumentPayload:
    file_bytes: bytes
    filename: str
    mime_type: str


@dataclass
class ImagePayload:
    file_bytes: bytes
    mime_type: str = "image/jpeg"


@dataclass
class VoicePayload:
    file_bytes: bytes
    mime_type: str = "audio/ogg"


@dataclass
class IngressPayload:
    """What the pipeline receives — platform-agnostic."""
    user_id: str                                # resolved before payload is built
    phone: str
    message: str | None = None                  # text body or caption
    message_type: str = "text"                  # text | voice | image | document
    document: DocumentPayload | None = None
    image: ImagePayload | None = None
    voice: VoicePayload | None = None
    source: str = "whatsapp"                    # whatsapp | web | api
    # Platform metadata (opaque to pipeline, passed through for delivery)
    platform_message_id: str | None = None      # wa_message_id, etc.
    platform_profile_name: str | None = None
    reply_to_id: str | None = None              # swipe-reply context
