from __future__ import annotations

import logging

from claude_agent_sdk import tool

from ..hooks import _CURRENT_USER_ID
from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)

@tool(
    "update_dashboard",
    (
        "Recompose the user's home dashboard from current state and persist "
        "it. Use when the user explicitly asks for a fresh read on their "
        "day ('redo my dashboard', 'refresh my home screen') or when a "
        "genuine state shift just landed (a major open loop closed, a new "
        "tracker started, a permission granted) and the previous manifest "
        "is now wrong. Does NOT change WhatsApp output — purely updates "
        "the web dashboard. Do NOT use to acknowledge a small action, "
        "after every recall, or when nothing material has changed since "
        "the last manifest. Returns a one-line confirmation."
    ),
    {
        "type": "object",
        "properties": {
            "trigger": {
                "type": "string",
                "description": (
                    "Short label for why this recompose was fired, e.g. "
                    "'manual', 'open_loop_closed', 'integration_connected'. "
                    "Stored alongside the manifest for debugging."
                ),
            }
        },
        "required": ["trigger"],
    },
)
async def update_dashboard(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("dashboard: no user_id in scope.")
    trigger = ""
    if isinstance(args, dict):
        trigger = str(args.get("trigger") or "").strip()
    if not trigger:
        trigger = "manual"
    try:
        from backend.dashboard.compose import compose_manifest
        from backend.dashboard.store import upsert_manifest
    except Exception:
        logger.exception("update_dashboard: import failed")
        return text_content("dashboard: subsystem unavailable.")
    try:
        plan = await compose_manifest(user_id=user_id, trigger=trigger)
    except Exception:
        logger.exception("update_dashboard: compose raised user_id=%s", user_id)
        return text_content("dashboard: compose failed (logged).")
    if plan is None:
        return text_content("dashboard: compose failed (logged).")
    try:
        await upsert_manifest(user_id, plan, trigger=trigger)
    except Exception:
        logger.exception("update_dashboard: upsert raised user_id=%s", user_id)
        return text_content("dashboard: persist failed (logged).")
    thesis_preview = (plan.thesis or "").strip()[:60]
    return text_content(f"dashboard updated · {thesis_preview}")


def mint_dashboard_url(user_id: str, *, reason: str = "user_request") -> str | None:
    """Mint a fresh 5-minute magic link for the user's dashboard.

    Returns the URL on success, None when the subsystem is unavailable or
    DASHBOARD_BASE_URL is not configured. Logs at info on success, warning
    on missing config, exception on mint failure. Used by both the
    send_dashboard_link tool and the deterministic first-message path in
    donna_runtime.brain.
    """
    if not user_id:
        return None
    try:
        import os
        from backend.auth.tokens import MAGIC_TTL_S, make_magic_token
    except Exception:
        logger.exception("mint_dashboard_url: import failed")
        return None
    base = (os.environ.get("DASHBOARD_BASE_URL") or "").rstrip("/")
    if not base:
        logger.warning("mint_dashboard_url: DASHBOARD_BASE_URL not set")
        return None
    try:
        token = make_magic_token(user_id)
    except Exception:
        logger.exception("mint_dashboard_url: token mint failed")
        return None
    url = f"{base}/auth/magic?t={token}"
    logger.info(
        "dashboard link issued: user_id=%s reason=%s ttl=%ds",
        user_id[:8], reason, MAGIC_TTL_S,
    )
    return url


@tool(
    "send_dashboard_link",
    (
        "Generate a fresh 5-minute magic link to the user's dashboard. "
        "Use when (a) the user explicitly asks ('send my dashboard', "
        "'open my home screen', 'where can i see all this'), (b) a "
        "turn just produced something live and specific worth seeing "
        "there now — a loop closed, a streak ticked, an attention went "
        "live, a tracker hit a milestone, or the user just offloaded a "
        "concrete thing for the first time, or (c) you are on a "
        "proactive turn after sustained user silence (~2+ hours post-"
        "onboarding) and the dashboard has something concrete to anchor "
        "on. Anchor your reply on the specific thing, then deliver the "
        "URL as a `cta_url` send_burst item with display_text='open "
        "dashboard' — never as plain text. Valid 5 minutes. Do NOT use "
        "on Day 1, on tiny acknowledgements, after every dashboard "
        "update, or as a generic status ping — that trains the user "
        "the link is noise."
    ),
    {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Short label for why the link was issued, e.g. "
                    "'first_message', 'user_request'. Logged for debugging; "
                    "not shown to the user."
                ),
            }
        },
        "required": ["reason"],
    },
)
async def send_dashboard_link(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("dashboard link: no user_id in scope.")
    reason = ""
    if isinstance(args, dict):
        reason = str(args.get("reason") or "").strip()
    reason = reason or "user_request"
    url = mint_dashboard_url(user_id, reason=reason)
    if url is None:
        return text_content("dashboard link: not available.")
    return text_content(
        f"link: {url} · valid 5 min · reason={reason}\n"
        f"deliver as cta_url item: "
        f"{{type:'cta_url', body:'<anchor>', display_text:'open dashboard', url:'{url}'}}"
    )

