from __future__ import annotations

from claude_agent_sdk import tool

from ..hooks import _CURRENT_TRACE, _fire_memory_hooks
from ..langsmith_tracing import traceable
from ..tool_logic import send_burst_result
from ._shared import _current_user_id

SEND_BURST_INPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "description": (
                "Ordered list of UI items to render as one WhatsApp turn. "
                "Items render in order. At most 3 non-delay items per burst. "
                "Voice: lowercase, no em dashes. Each text body <=200 chars typical."
            ),
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["type", "body"],
                        "properties": {
                            "type": {"const": "text"},
                            "body": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1000,
                                "description": "Plain text bubble. Lowercase, no em dashes.",
                            },
                            "reply_to_message_id": {
                                "type": ["string", "null"],
                                "description": (
                                    "Optional WA message id to quote-reply to. "
                                    "Omit unless you specifically want this bubble "
                                    "to visually thread to a prior message."
                                ),
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "buttons"],
                        "properties": {
                            "type": {"const": "cta"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "buttons": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "description": (
                                    "1-3 reply buttons. Tapping a button sends "
                                    "its title back as the user's next inbound text. "
                                    "Use ONLY when the answer is a small known set "
                                    "(yes/no, pick from <=3 options). Not for "
                                    "open-ended questions."
                                ),
                                "items": {
                                    "type": "object",
                                    "required": ["id", "title"],
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 64,
                                            "description": "Short stable machine id, e.g. 'confirm_tz'.",
                                        },
                                        "title": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 20,
                                            "description": "User-facing label, <=20 chars.",
                                        },
                                    },
                                },
                            },
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "display_text", "url"],
                        "properties": {
                            "type": {"const": "cta_url"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "display_text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 20,
                                "description": "Label on the URL button (e.g. 'Open', 'Connect').",
                            },
                            "url": {"type": "string", "minLength": 1, "format": "uri"},
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type", "body", "button_label", "sections"],
                        "properties": {
                            "type": {"const": "list"},
                            "body": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "button_label": {"type": "string", "minLength": 1, "maxLength": 20},
                            "sections": {
                                "type": "array",
                                "minItems": 1,
                                "description": (
                                    "Up to 10 rows total across all sections. "
                                    "Use when there are >3 options to pick from. Rare."
                                ),
                                "items": {
                                    "type": "object",
                                    "required": ["title", "rows"],
                                    "properties": {
                                        "title": {"type": "string", "maxLength": 24},
                                        "rows": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "required": ["id", "title"],
                                                "properties": {
                                                    "id": {"type": "string", "maxLength": 64},
                                                    "title": {"type": "string", "maxLength": 24},
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"const": "image"},
                            "url": {
                                "type": "string",
                                "minLength": 1,
                                "format": "uri",
                                "description": (
                                    "Publicly accessible URL. Use this OR media_id, "
                                    "never both. Never invent a URL."
                                ),
                            },
                            "media_id": {
                                "type": "string",
                                "minLength": 1,
                                "description": (
                                    "WhatsApp media id returned by the image tool. "
                                    "Use this when threading a generated image into "
                                    "the burst. Use this OR url, never both."
                                ),
                            },
                            "caption": {"type": "string", "maxLength": 1024},
                            "reply_to_message_id": {"type": ["string", "null"]},
                        },
                        "oneOf": [
                            {"required": ["url"]},
                            {"required": ["media_id"]},
                        ],
                    },
                    {
                        "type": "object",
                        "required": ["type", "seconds"],
                        "properties": {
                            "type": {"const": "delay"},
                            "seconds": {
                                "type": "number",
                                "minimum": 0.5,
                                "maximum": 4.0,
                                "description": (
                                    "Pause before next item, 0.5-4.0s. Use sparingly "
                                    "for pacing (greeting before a question, ack "
                                    "before advice). Never first or last item."
                                ),
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "const": "voice_response",
                                "description": (
                                    "VOICE-NOTE FLAG. Place first in the burst "
                                    "to deliver the whole burst as one WhatsApp "
                                    "voice note. The text bodies of the other "
                                    "items are concatenated and synthesized. "
                                    "Voice is RARE — text is the default reply "
                                    "mode in every turn. USE WHEN: the user "
                                    "explicitly asked for voice ('send me a "
                                    "voice', 'voice me', 'say it out loud'); "
                                    "the reply is genuinely personal and "
                                    "emotionally weighted (a pep talk, a soft "
                                    "check-in at a hard moment, a longform "
                                    "reflective read more than two sentences). "
                                    "DO NOT USE WHEN: the inbound was a voice "
                                    "note but the reply is short, factual, or "
                                    "operational (the user dictated for their "
                                    "own convenience, not to request voice "
                                    "back — mirroring is wrong); the answer is "
                                    "a fact, a number, a time, a calendar "
                                    "item, a link, or a list; the burst "
                                    "includes a cta, cta_url, list, image, or "
                                    "document item (those cannot combine with "
                                    "voice); the user is in crisis or panic "
                                    "(text is more legible under stress); a "
                                    "one or two-word ack would do (a 4-word "
                                    "voice note is annoying). Hard cap 600 "
                                    "chars. On any synthesis failure the "
                                    "burst falls back to text. Saying 'here "
                                    "is a voice message' in text without this "
                                    "item is wrong."
                                ),
                            },
                        },
                    },
                ]
            },
        },
    },
}

@tool(
    "send_burst",
    (
        "TERMINATOR — the ONLY way to end a turn. Exactly one send_burst per "
        "turn, never twice, no silent exit. For ambient chatter, emit a "
        "single minimal text item ('k', 'noted') — still terminates. See "
        "`# HOW YOU USE WHATSAPP` in the system prompt for which widget to "
        "pick. A downstream voice filter strips em dashes, semicolons, and "
        "banned filler phrases and logs a violation, so produce clean text "
        "on first write."
    ),
    SEND_BURST_INPUT_SCHEMA,
)
@traceable(name="donna.tool.send_burst", run_type="tool")
async def send_burst(args):
    try:
        raw_messages = args.get("messages") if isinstance(args, dict) else []
        item_types = [
            (m.get("type") if isinstance(m, dict) else type(m).__name__)
            for m in (raw_messages or [])
        ]
        logger.info("send_burst.invoke: types=%s count=%d", item_types, len(item_types))
    except Exception:
        pass
    result = await send_burst_result(args)
    from ..voice_synth import maybe_synthesize_voice
    await maybe_synthesize_voice()
    _fire_memory_hooks(_CURRENT_TRACE.get(), args)
    return result

