from __future__ import annotations

import hashlib
import json
import logging

from claude_agent_sdk import tool

from ..hooks import set_image_prompt_hash
from ..langsmith_tracing import traceable
from ..tool_logic import compose_image_prompt, text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)

@tool(
    "image",
    (
        "Generate a warm hand-drawn illustration and return a handle for "
        "send_burst. Takes intent (one sentence of what the picture should "
        "say) and caption (what Donna will say under it, in her voice). The "
        "tool composes the image prompt from the user's facts; Donna does "
        "not write image prompts. Returns a media_id to thread into "
        "send_burst as an image item. "
        "WHEN TO USE: any time the user explicitly asks for an image, "
        "picture, drawing, or illustration of anything. Examples: 'send me "
        "an image of a banana', 'draw me a sunset', 'make a picture of x', "
        "'show me y'. The user asking IS the trigger. Do NOT refuse, do NOT "
        "second-guess, do NOT lecture about when you draw. Just call the "
        "tool. Also use proactively when a milestone or closed loop earns a "
        "picture (rare). "
        "WHEN NOT TO USE: photorealism of the user or any real person by "
        "name (hard rail), or for diagrams, receipts, or data tables (those "
        "are text). "
        "Hard rails the tool enforces in addition: one image per turn, "
        "ever. A 6h cooldown and a 3/week cap are enforced by the "
        "PreToolUse hook — expect a deny string when you overreach and "
        "fall through to text. On any failure (provider down, safety "
        "reject, cap hit), the return string tells you to skip the image "
        "and reply in text."
    ),
    {
        "type": "object",
        "required": ["intent", "caption"],
        "properties": {
            "intent": {
                "type": "string",
                "description": "One short sentence of what the picture should say.",
            },
            "caption": {
                "type": "string",
                "description": "The WhatsApp caption under the image, in Donna's voice.",
            },
        },
    },
)
@traceable(name="donna.tool.image", run_type="tool")
async def image(args):
    from ..image_client import (
        ImageProviderError,
        ImageSafetyError,
        ImageUploadError,
        generate_and_upload,
    )

    user_id = _current_user_id()
    intent = (args.get("intent") or "").strip() if isinstance(args, dict) else ""
    caption = (args.get("caption") or "").strip() if isinstance(args, dict) else ""

    if not intent or not caption:
        return text_content(
            "image unavailable: intent and caption are both required. go text."
        )
    if not user_id:
        return text_content(
            "image unavailable: runtime user scope missing. go text."
        )

    try:
        composed_prompt = await compose_image_prompt(user_id, intent)
    except ValueError:
        return text_content("image unavailable: intent invalid. go text.")

    prompt_hash = hashlib.sha256(composed_prompt.encode("utf-8")).hexdigest()
    set_image_prompt_hash(prompt_hash)

    from delivery.whatsapp import WhatsAppChannel

    wa = WhatsAppChannel()

    try:
        result = await generate_and_upload(composed_prompt, wa)
    except ImageSafetyError as e:
        logger.info("image.safety_reject: %s", e)
        return text_content(
            "image rejected by safety filter. rewrite intent without the "
            "flagged element, or go text."
        )
    except ImageUploadError as e:
        logger.warning("image.upload_failed: %s", e)
        return text_content(
            "image unavailable: whatsapp media upload failed. skip the image, "
            "reply with text."
        )
    except ImageProviderError as e:
        logger.warning("image.provider_failed: %s", e)
        return text_content(
            "image unavailable: provider timeout. skip the image, reply with text."
        )
    except Exception:
        logger.exception("image tool unexpected failure")
        return text_content("image unavailable: unexpected failure. go text.")

    return text_content(
        f"image ready: {result.media_id}. use it in send_burst as an image "
        f"item with media_id={result.media_id}, caption unchanged."
    )

