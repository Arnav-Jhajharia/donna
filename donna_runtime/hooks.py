from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Mapping, Sequence
from typing import Iterator

from .langsmith_tracing import traceable
from .observability import emit, emit_hook_deny
from .tracing import TERMINATOR_TOOL_SUFFIXES, TurnTrace

logger = logging.getLogger(__name__)


_CURRENT_TRACE: ContextVar[TurnTrace | None] = ContextVar("donna_current_trace", default=None)
_CURRENT_USER_ID: ContextVar[str | None] = ContextVar("donna_current_user_id", default=None)
_OUTBOUND_BUFFER: ContextVar[list | None] = ContextVar("donna_outbound_buffer", default=None)
_CHAT_ALREADY_PERSISTED: ContextVar[bool] = ContextVar(
    "donna_chat_already_persisted", default=False
)
# Turn-scoped set of (tool_name, args_hash) to detect within-turn duplicate
# calls on write tools. Populated in PreToolUse, reset per turn by the runner.
_TURN_WRITE_SIGNATURES: ContextVar[set[tuple[str, str]] | None] = ContextVar(
    "donna_turn_write_signatures", default=None
)

# Stashed on TurnTrace.prompt_metadata rather than a ContextVar because the
# image tool runs under @langsmith.traceable, which snapshots the context —
# ContextVar writes inside the wrapped callable don't propagate back to the
# post-hook. Mutating a shared mutable object (the trace) does.
_IMAGE_PROMPT_HASH_KEY = "_image_prompt_hash"

# Tools whose double-call within a single turn would create duplicate data.
# Reads are intentionally excluded: repeating a read is wasteful but safe.
_IDEMPOTENCY_GUARDED_TOOLS: tuple[str, ...] = (
    "log_observation",
    "track_open_loop",
    "remember",
    "attend",
    "cancel_attention",
    "snooze_attention",
)

_PENDING_HOOK_TASKS: set[asyncio.Task] = set()


def _canonical_args_hash(tool_input: object) -> str:
    """Stable hash of tool args. Identical JSON values → identical hash."""
    try:
        payload = json.dumps(tool_input, sort_keys=True, default=str)
    except Exception:
        payload = repr(tool_input)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _tool_short_name(full_name: str) -> str:
    """Strip 'mcp__donna__' prefix if present to compare against guard list."""
    return full_name.split("__")[-1] if full_name else ""


def _preview_value(value: object, *, max_chars: int = 4000) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + " ... <truncated>"
    if isinstance(value, Mapping):
        return {
            str(k): _preview_value(v, max_chars=max(200, max_chars // 2))
            for k, v in list(value.items())[:30]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_preview_value(v, max_chars=max(200, max_chars // 2)) for v in list(value)[:20]]
    try:
        text = json.dumps(value, default=str)
    except Exception:
        text = repr(value)
    return text if len(text) <= max_chars else text[:max_chars] + " ... <truncated>"


async def drain_memory_hooks() -> None:
    if not _PENDING_HOOK_TASKS:
        return
    await asyncio.gather(*list(_PENDING_HOOK_TASKS), return_exceptions=True)


@contextmanager
def trace_hook_context(
    trace: TurnTrace,
    user_id: str | None = None,
    chat_already_persisted: bool = False,
) -> Iterator[None]:
    trace_token = _CURRENT_TRACE.set(trace)
    user_token = _CURRENT_USER_ID.set(user_id)
    chat_token = _CHAT_ALREADY_PERSISTED.set(chat_already_persisted)
    sig_token = _TURN_WRITE_SIGNATURES.set(set())
    ack_token = _SLOW_ACK_FIRED.set(False)
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(trace_token)
        _CURRENT_USER_ID.reset(user_token)
        _CHAT_ALREADY_PERSISTED.reset(chat_token)
        _TURN_WRITE_SIGNATURES.reset(sig_token)
        _SLOW_ACK_FIRED.reset(ack_token)


def set_image_prompt_hash(prompt_hash: str | None) -> None:
    """Stashed on the current TurnTrace so PostToolUse can recover it even
    though the image tool runs inside a langsmith-copied context."""
    trace = _CURRENT_TRACE.get()
    if trace is None:
        return
    trace.prompt_metadata[_IMAGE_PROMPT_HASH_KEY] = prompt_hash


def _pop_image_prompt_hash() -> str | None:
    trace = _CURRENT_TRACE.get()
    if trace is None:
        return None
    return trace.prompt_metadata.pop(_IMAGE_PROMPT_HASH_KEY, None)


def _is_terminator(tool_name: str) -> bool:
    return bool(tool_name) and tool_name.endswith(TERMINATOR_TOOL_SUFFIXES)


def _extract_tool_response_text(tool_response: object) -> str:
    """Flatten a claude-agent-sdk tool_response into the text Donna saw."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, Mapping):
        content = tool_response.get("content")
        return _extract_tool_response_text(content)
    if isinstance(tool_response, Sequence) and not isinstance(
        tool_response, (str, bytes, bytearray)
    ):
        parts: list[str] = []
        for block in tool_response:
            if isinstance(block, Mapping) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(tool_response)


def _classify_image_outcome(response_text: str) -> str | None:
    """Map the image tool's return text to a cap-event status.

    Returns None for caller-side validation failures (empty intent/caption,
    missing user scope, invalid intent) — those are not cap-relevant terminal
    outcomes and shouldn't pollute `image_tool_events`."""
    text = (response_text or "").lower().strip()
    if not text:
        return None
    if text.startswith("image ready:"):
        return "sent"
    if "rejected by safety filter" in text:
        return "failed_safety"
    if text.startswith("image unavailable:"):
        if "intent" in text or "runtime user scope" in text:
            return None
        return "failed_provider"
    return None


async def pre_tool_hook(input_data, tool_use_id, context):
    trace = _CURRENT_TRACE.get()
    hook_input = _hook_payload(input_data, tool_use_id)
    if trace is not None:
        trace.record_hook_pre(hook_input, str(tool_use_id))
        tool_name = str(hook_input.get("tool_name") or hook_input.get("name") or "")
        tool_input_dict = hook_input.get("tool_input") or {}
        emit(
            "tool.call",
            tool=tool_name,
            tool_short=_tool_short_name(tool_name),
            call_id=str(tool_use_id),
            input_keys=(
                list(tool_input_dict.keys())[:20]
                if isinstance(tool_input_dict, dict)
                else []
            ),
            input_preview=_preview_value(tool_input_dict),
        )
        if _is_terminator(tool_name) and trace.has_terminal_tool_call():
            logger.warning(
                "pre_tool_hook: blocking second terminator %s (turn already terminated)",
                tool_name,
            )
            emit_hook_deny(
                tool_name=tool_name,
                decision_kind="double_terminator",
                reason="Turn already ended with a terminator tool.",
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Turn already ended with a terminator tool. "
                        "Only one terminator per turn."
                    ),
                }
            }

        short = _tool_short_name(tool_name)
        if short == "send_burst":
            inject = _maybe_inject_voice_response(hook_input, trace)
            if inject is not None:
                return inject
        if short == "image":
            deny = await _image_pre_tool_check(tool_name)
            if deny is not None:
                return deny
            _fire_image_ack(trace)
        if short in _SLOW_TOOL_NAMES:
            _fire_slow_tool_ack(trace)
        if short in _IDEMPOTENCY_GUARDED_TOOLS:
            signatures = _TURN_WRITE_SIGNATURES.get()
            if signatures is not None:
                signature = (short, _canonical_args_hash(hook_input.get("tool_input") or {}))
                if signature in signatures:
                    logger.warning(
                        "pre_tool_hook: blocking duplicate %s call within turn (args match prior call)",
                        short,
                    )
                    emit_hook_deny(
                        tool_name=tool_name,
                        decision_kind="duplicate_write",
                        reason=f"{short} already called with identical args this turn.",
                    )
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                f"{short} already called with identical args this turn. "
                                "Use the prior result instead of re-calling."
                            ),
                        }
                    }
                signatures.add(signature)
    await trace_pre_tool_hook(hook_input)
    return {}


async def post_tool_hook(input_data, tool_use_id, context):
    trace = _CURRENT_TRACE.get()
    hook_input = _hook_payload(input_data, tool_use_id)
    if trace is not None:
        trace.record_hook_post(hook_input, str(tool_use_id))

    tool_name = str(hook_input.get("tool_name") or "")
    short_name = _tool_short_name(tool_name)
    if short_name == "image":
        tool_response = (
            input_data.get("tool_response") if isinstance(input_data, Mapping) else None
        )
        await _image_post_tool_record(tool_name, tool_response)

    if short_name == "connect_integration":
        tool_response = (
            input_data.get("tool_response") if isinstance(input_data, Mapping) else None
        )
        _maybe_spawn_oauth_watcher(tool_response)

    await trace_post_tool_hook(hook_input)

    return {}


def _maybe_inject_voice_response(
    hook_input: Mapping[str, object],
    trace: TurnTrace | None,
) -> dict | None:
    """Force the voice_response marker into send_burst when the user asked for voice.

    Returns a PreToolUse output dict (with `updatedInput`) when injection is
    needed, or None to let the call proceed unchanged. The model still picks
    the text bodies; we only guarantee the marker is present.
    """
    if trace is None:
        return None
    from .voice_intent import detect_voice_request

    if not detect_voice_request(getattr(trace, "user_message", "") or ""):
        return None

    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return None
    messages = tool_input.get("messages")
    if not isinstance(messages, Sequence) or isinstance(messages, str):
        return None

    has_marker = any(
        isinstance(m, Mapping) and m.get("type") == "voice_response"
        for m in messages
    )
    if has_marker:
        return None

    new_messages: list = [{"type": "voice_response"}, *messages]
    new_input = {**tool_input, "messages": new_messages}
    logger.info(
        "pre_tool_hook: injected voice_response marker (user asked for voice, model emitted text-only burst)"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": new_input,
        }
    }


_IMAGE_ACK_TEXT = "drawing this, one sec"
_IMAGE_ACK_EMOJI = "🎨"

# Tools that take >5s in the median case. Reacting ⏳ on the user's
# inbound message gives them a non-verbal "i saw this, working on it"
# without breaking the prompt rule against announcing tool calls.
_SLOW_TOOL_NAMES: frozenset[str] = frozenset({
    "recall",
    "recall_episodic",
    "recall_graph",
    "recall_chat_thread",
    "research",
    "agentic_web_search",
    "web_search",
    "composio_search_tools",
    "composio_execute_tool",
    "read_gmail_thread",
    "search_gmail",
})
_SLOW_TOOL_ACK_EMOJI = "⏳"
# Per-turn flag (via ContextVar) so the slow-tool ack only fires once
# per inbound message even when the BRAIN calls multiple slow tools in
# a row. Cleared by ``trace_hook_context`` between turns.
_SLOW_ACK_FIRED: ContextVar[bool] = ContextVar(
    "donna_slow_ack_fired", default=False
)


def _fire_slow_tool_ack(trace: TurnTrace | None) -> None:
    """React ⏳ on the user's inbound message when a slow tool starts.

    Idempotent per (user, message) — only the first slow-tool call in a
    turn fires the reaction. Subsequent calls in the same turn are
    silently skipped so we don't burn API quota overwriting the same
    emoji on the same message.
    """
    if trace is None:
        return
    phone = getattr(trace, "user_phone", None)
    inbound_msg_id = getattr(trace, "inbound_wa_message_id", None)
    if not (phone and inbound_msg_id):
        return
    if _SLOW_ACK_FIRED.get():
        return
    _SLOW_ACK_FIRED.set(True)

    async def _do_react() -> None:
        try:
            from delivery.whatsapp import WhatsAppChannel
        except Exception:
            logger.exception("slow tool ack: import failed (non-fatal)")
            return
        wa = WhatsAppChannel()
        try:
            await wa.send_reaction(phone, inbound_msg_id, _SLOW_TOOL_ACK_EMOJI)
        except Exception:
            logger.warning("slow tool ack: react failed (non-fatal)")

    try:
        task = asyncio.create_task(_do_react())
        _PENDING_HOOK_TASKS.add(task)
        task.add_done_callback(_PENDING_HOOK_TASKS.discard)
    except RuntimeError:
        pass


def _fire_image_ack(trace: TurnTrace | None) -> None:
    """Fire reaction + 'drawing this' text on the user's inbound message.

    Both calls are fire-and-forget so they never block the image tool.
    Skips silently when phone or message_id are missing (e.g., CLI runs).
    """
    if trace is None:
        return
    phone = getattr(trace, "user_phone", None)
    inbound_msg_id = getattr(trace, "inbound_wa_message_id", None)
    if not phone:
        return

    async def _do_ack() -> None:
        try:
            from delivery.messages import TextMessage
            from delivery.whatsapp import WhatsAppChannel
        except Exception:
            logger.exception("image ack: import failed (non-fatal)")
            return
        wa = WhatsAppChannel()
        try:
            await asyncio.gather(
                wa.send_reaction(phone, inbound_msg_id, _IMAGE_ACK_EMOJI),
                wa.send(phone, TextMessage(body=_IMAGE_ACK_TEXT)),
                return_exceptions=True,
            )
        except Exception:
            logger.warning("image ack: send failed (non-fatal)")

    try:
        task = asyncio.create_task(_do_ack())
        _PENDING_HOOK_TASKS.add(task)
        task.add_done_callback(_PENDING_HOOK_TASKS.discard)
    except RuntimeError:
        # No running loop (e.g., in some unit tests) — drop silently.
        pass


# Legacy product alias -> Composio toolkit slug. Kept so older
# connect_integration callers (returning {urls: {gmail, calendar, drive}})
# still resolve correctly. New callers return urls keyed by toolkit slug.
_LEGACY_PRODUCT_ALIAS = {
    "calendar": "googlecalendar",
    "drive": "googledrive",
    # gmail and other slugs already match toolkit names verbatim
}


def _extract_connect_toolkits(tool_response: object) -> list[str] | None:
    """Pull the toolkits the user is being asked to connect from the
    connect_integration response.

    Prefers the explicit ``toolkits: [slug, ...]`` field. Falls back to
    the legacy ``urls`` mapping (keys may be friendly product names like
    "gmail"/"calendar"/"drive" — translated back to toolkit slugs).
    Returns None when nothing parseable is present.
    """
    if not isinstance(tool_response, Mapping):
        return None
    explicit = tool_response.get("toolkits")
    if isinstance(explicit, Sequence) and not isinstance(
        explicit, (str, bytes, bytearray)
    ):
        slugs = [str(t).strip() for t in explicit if str(t).strip()]
        if slugs:
            return slugs
    urls = tool_response.get("urls")
    if isinstance(urls, Mapping):
        return [_LEGACY_PRODUCT_ALIAS.get(str(k), str(k)) for k in urls.keys()]
    return None


def _maybe_spawn_oauth_watcher(tool_response: object) -> None:
    """Fire-and-forget: launch the OAuth completion watcher when
    connect_integration has just emitted redirect URLs.

    Polls for ANY toolkit (google or otherwise) so the integrations table
    flips connected without waiting on Composio's webhook. The watcher
    itself decides when the gmail bootstrap pipeline should fire.
    """
    user_id = _CURRENT_USER_ID.get()
    if not user_id:
        return
    toolkits = _extract_connect_toolkits(tool_response)
    if not toolkits:
        return

    async def _do_watch() -> None:
        try:
            from backend.integrations.oauth_watcher import (
                watch_oauth_and_bootstrap,
            )
        except Exception:
            logger.exception("oauth watcher: import failed (non-fatal)")
            return
        try:
            await watch_oauth_and_bootstrap(
                user_id=user_id, toolkits=toolkits
            )
        except Exception:
            logger.exception("oauth watcher: run failed (non-fatal)")

    try:
        task = asyncio.create_task(_do_watch())
        _PENDING_HOOK_TASKS.add(task)
        task.add_done_callback(_PENDING_HOOK_TASKS.discard)
    except RuntimeError:
        # No running loop (e.g., some unit tests) — drop silently.
        pass


async def _image_pre_tool_check(tool_name: str) -> dict | None:
    """Enforce cooldown + weekly cap. Returns a deny payload or None (allow)."""
    user_id = _CURRENT_USER_ID.get()
    if not user_id:
        return None
    try:
        from backend.memory.tools import image_caps
    except Exception:
        logger.exception("pre_tool_hook: image_caps import failed — allowing")
        return None

    try:
        decision = await image_caps.check(user_id)
    except Exception:
        logger.exception("pre_tool_hook: image_caps.check raised — allowing")
        return None

    if decision.allowed:
        return None

    try:
        await image_caps.record(user_id, decision.status, prompt_hash=None)
    except Exception:
        logger.exception("pre_tool_hook: image_caps.record(deny) failed")

    emit_hook_deny(
        tool_name=tool_name,
        decision_kind=decision.status or "image_cap",
        reason=decision.reason,
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": decision.reason,
        }
    }


async def _image_post_tool_record(tool_name: str, tool_response: object) -> None:
    """Record a terminal outcome and emit `image.generated`."""
    user_id = _CURRENT_USER_ID.get()
    if not user_id:
        _pop_image_prompt_hash()
        return

    response_text = _extract_tool_response_text(tool_response)
    status = _classify_image_outcome(response_text)
    prompt_hash = _pop_image_prompt_hash()
    if status is None:
        return

    try:
        from backend.memory.tools import image_caps
        await image_caps.record(user_id, status, prompt_hash)
    except Exception:
        logger.exception("post_tool_hook: image_caps.record failed")

    emit(
        "image.generated",
        tool=tool_name,
        status=status,
        prompt_hash=prompt_hash,
    )


def _fire_memory_hooks(trace: TurnTrace | None, send_burst_input: dict) -> None:
    user_id = _CURRENT_USER_ID.get()
    if not user_id or trace is None:
        return
    try:
        from backend.memory.hooks import ALL_HOOKS
    except Exception:
        logger.exception("post_tool_hook: memory hooks import failed")
        return

    outbound = send_burst_input.get("messages") or []
    if not isinstance(outbound, list):
        outbound = []
    from .tool_logic import render_burst_items_text
    rendered_outbound = render_burst_items_text(outbound)
    tool_names = [c["tool"] for c in trace.tool_calls]
    ctx = {
        "user_id": user_id,
        "inbound": trace.user_message,
        "outbound": rendered_outbound,
        "tool_names": tool_names,
        "terminator": "send_burst",
        "user_facts": {},
        "chat_already_persisted": _CHAT_ALREADY_PERSISTED.get(),
    }
    for hook in ALL_HOOKS:
        try:
            task = asyncio.create_task(hook(ctx))
        except RuntimeError:
            logger.debug("no running loop — skipping memory hook %s", hook.__module__)
            continue
        _PENDING_HOOK_TASKS.add(task)
        task.add_done_callback(_PENDING_HOOK_TASKS.discard)


@traceable(name="donna.hook.pre_tool", run_type="tool")
async def trace_pre_tool_hook(payload: dict[str, object]) -> dict[str, object]:
    return payload


@traceable(name="donna.hook.post_tool", run_type="tool")
async def trace_post_tool_hook(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _hook_payload(input_data, tool_use_id) -> dict[str, object]:
    raw = dict(input_data)
    return {
        "tool_use_id": str(tool_use_id),
        "tool_name": raw.get("tool_name") or raw.get("name") or "unknown",
        "tool_input": raw.get("tool_input") or raw.get("input") or {},
    }
