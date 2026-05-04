"""SDK @tool wrappers around the typed Tier 3 tool functions.

The typed functions in donna_runtime/tools_tier3.py are pure Python with
proper type annotations and defensive validations. This module wraps each
one as a Claude Agent SDK MCP tool so the brain runtime can invoke them.

Why split: testing the typed functions doesn't require the SDK's MCP
machinery; testing the wrappers verifies SDK packaging and error
handling. Each wrapper:
  - Declares the @tool metadata (name, description, JSON Schema)
  - Pulls args out of the SDK's dict payload
  - Calls the typed function
  - Packages the result as SDK content blocks, or returns isError=True
    on validation failure
"""
from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from donna_runtime.tools_tier3 import (
    kill_attention,
    quick_check,
    read_external,
    reshape_attention,
    send_burst,
    skip,
)


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    """Package a typed-function outcome dict as an SDK tool result."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, default=str)}
        ]
    }


def _err(message: str) -> dict[str, Any]:
    """Package a validation error as an SDK tool result with isError=True."""
    return {
        "content": [{"type": "text", "text": f"validation_error: {message}"}],
        "isError": True,
    }


# ---- skip ------------------------------------------------------------------

_SKIP_DESCRIPTION = (
    "Explicit silence. First-class outcome — silence is correct when "
    "fresh signal shows the moment is dead, the topic is already covered, "
    "or your editorial read is that this fire would degrade trust. Do not "
    "use when you'd rather hold the message — use send_burst with "
    "push=false and surface_at instead."
)

_SKIP_INPUT_SCHEMA = {
    "type": "object",
    "required": ["reason"],
    "properties": {
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "One short sentence explaining why this fire is being silenced.",
        },
    },
}


@tool("skip", _SKIP_DESCRIPTION, _SKIP_INPUT_SCHEMA)
async def skip_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await skip(reason=str(args.get("reason") or ""))
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- kill_attention --------------------------------------------------------

_KILL_DESCRIPTION = (
    "Terminate a live attention. Sets status=killed, cancels future "
    "schedule rows. Permanent. Use when fresh signal shows the user "
    "already did the thing, the moment is permanently gone, or the spec "
    "was wrong from the start. Do not use for transient stale (use "
    "reshape_attention with next_fire_at instead)."
)

_KILL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["attention_id", "reason"],
    "properties": {
        "attention_id": {
            "type": "string",
            "minLength": 1,
            "description": "The attention id to terminate.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "One short sentence for the audit log.",
        },
    },
}


@tool("kill_attention", _KILL_DESCRIPTION, _KILL_INPUT_SCHEMA)
async def kill_attention_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await kill_attention(
            attention_id=str(args.get("attention_id") or ""),
            reason=str(args.get("reason") or ""),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- reshape_attention -----------------------------------------------------

_RESHAPE_DESCRIPTION = (
    "Modify the live attention spec without firing. Use when world "
    "changed but the spec is still useful (push to tomorrow, downgrade "
    "urgency, fold cadence). Do not use when the right action is to fire "
    "now (use send_burst), or when the spec is permanently moot (use "
    "kill_attention). Must include at least one of: next_fire_at, "
    "surface_level, cadence_change."
)

_RESHAPE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["attention_id"],
    "properties": {
        "attention_id": {"type": "string", "minLength": 1},
        "next_fire_at": {
            "type": ["string", "null"],
            "description": "ISO-8601 datetime for the next fire. Null to leave unchanged.",
        },
        "surface_level": {
            "type": ["string", "null"],
            "enum": ["silent", "digest", "notify", "urgent", None],
        },
        "cadence_change": {
            "type": ["object", "null"],
            "description": "Narrow cadence params override (advanced).",
        },
    },
}


@tool("reshape_attention", _RESHAPE_DESCRIPTION, _RESHAPE_INPUT_SCHEMA)
async def reshape_attention_tool(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime

    next_fire_at = args.get("next_fire_at")
    parsed_dt = None
    if next_fire_at:
        try:
            parsed_dt = datetime.fromisoformat(str(next_fire_at))
        except ValueError as exc:
            return _err(f"next_fire_at not iso-8601: {exc}")

    try:
        result = await reshape_attention(
            attention_id=str(args.get("attention_id") or ""),
            next_fire_at=parsed_dt,
            surface_level=args.get("surface_level"),
            cadence_change=args.get("cadence_change"),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- send_burst ------------------------------------------------------------

_SEND_BURST_DESCRIPTION = (
    "Ship the proactive message. Channel is inline. Quadrants: "
    "push=true → WhatsApp ping; push=false → ambient (chat_messages "
    "only); push=false + surface_at='next_user_touch' → pending note "
    "surfaces in next reactive turn; push=false + surface_at='morning_brief' "
    "→ pending note tagged for tomorrow's morning brief. push=true with "
    "surface_at set is a contract violation."
)

_SEND_BURST_INPUT_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "required": ["type"],
            },
        },
        "push": {"type": "boolean", "default": True},
        "surface_at": {
            "type": ["string", "null"],
            "enum": ["next_user_touch", "morning_brief", None],
        },
    },
}


@tool("send_burst", _SEND_BURST_DESCRIPTION, _SEND_BURST_INPUT_SCHEMA)
async def send_burst_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await send_burst(
            messages=list(args.get("messages") or []),
            push=bool(args.get("push", True)),
            surface_at=args.get("surface_at"),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- quick_check -----------------------------------------------------------

_QUICK_CHECK_DESCRIPTION = (
    "One-shot web search to verify a specific factual claim or fetch a "
    "focused fact. Use when the event makes a claim that needs "
    "verification, or thought_youd_want needs a freshness check. Do not "
    "use for general research or exploration. HARD LIMIT: one call per "
    "turn. Cost: ~$0.005, ~1-2s."
)

_QUICK_CHECK_INPUT_SCHEMA = {
    "type": "object",
    "required": ["question"],
    "properties": {
        "question": {"type": "string", "minLength": 1, "maxLength": 500},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
    },
}


@tool("quick_check", _QUICK_CHECK_DESCRIPTION, _QUICK_CHECK_INPUT_SCHEMA)
async def quick_check_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await quick_check(
            question=str(args.get("question") or ""),
            max_results=int(args.get("max_results") or 3),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- read_external ---------------------------------------------------------

_READ_EXTERNAL_DESCRIPTION = (
    "Fresh state of one specific external resource by identifier. Use "
    "when you need fresh state of something specifically referenced by "
    "id, and that exact resource isn't in the pre-fetched fresh_signal "
    "block. Do not use when fresh_signal already has what you need. "
    "Cost: source-specific, ~0.5-2s."
)

_READ_EXTERNAL_INPUT_SCHEMA = {
    "type": "object",
    "required": ["source", "ref"],
    "properties": {
        "source": {
            "type": "string",
            "enum": [
                "gmail_thread",
                "calendar_event",
                "exa_url",
                "person_recent_chat",
            ],
        },
        "ref": {"type": "string", "minLength": 1},
    },
}


@tool("read_external", _READ_EXTERNAL_DESCRIPTION, _READ_EXTERNAL_INPUT_SCHEMA)
async def read_external_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await read_external(
            source=args.get("source"),  # type: ignore[arg-type]
            ref=str(args.get("ref") or ""),
        )
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result)


# ---- registry --------------------------------------------------------------

TIER3_SDK_TOOLS = (
    skip_tool,
    kill_attention_tool,
    reshape_attention_tool,
    send_burst_tool,
    quick_check_tool,
    read_external_tool,
)
