from __future__ import annotations

import logging

from claude_agent_sdk import tool

from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)

@tool(
    "send_login_otp",
    (
        "Generate a 6-digit login code the user can type on the dashboard's "
        "/auth/otp page. Use when the user explicitly asks for a login code "
        "('send me a code', 'i need to log in another way', 'i lost the "
        "link') or when the magic-link flow is broken on their end. Include "
        "the code verbatim in your send_burst reply and tell them it's "
        "valid for 10 minutes. After they verify, the dashboard session "
        "lasts 24 hours (longer than a magic-link session — that's the "
        "trade-off for typing a code). Do NOT use as the default login "
        "path; magic links are the primary surface. Returns the plaintext "
        "code (single-use, 10-min TTL)."
    ),
    {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Short label for why the OTP was issued, e.g. "
                    "'magic_link_failed', 'user_request'. Logged for "
                    "debugging; not shown to the user."
                ),
            }
        },
        "required": ["reason"],
    },
)
async def send_login_otp(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("login code: no user_id in scope.")
    reason = ""
    if isinstance(args, dict):
        reason = str(args.get("reason") or "").strip()
    reason = reason or "user_request"
    try:
        from backend.auth.otp import OTP_TTL_S, issue_otp
    except Exception:
        logger.exception("send_login_otp: import failed")
        return text_content("login code: subsystem unavailable.")
    try:
        code = await issue_otp(user_id)
    except Exception:
        logger.exception("send_login_otp: issue failed user_id=%s", user_id)
        return text_content("login code: issue failed.")
    logger.info(
        "send_login_otp issued: user_id=%s reason=%s ttl=%ds",
        user_id[:8], reason, OTP_TTL_S,
    )
    return text_content(
        f"code: {code} · valid 10 min · reason={reason}"
    )

