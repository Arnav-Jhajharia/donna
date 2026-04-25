from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
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

# Tools whose double-call within a single turn would create duplicate data.
# Reads are intentionally excluded: repeating a read is wasteful but safe.
_IDEMPOTENCY_GUARDED_TOOLS: tuple[str, ...] = (
    "log_observation",
    "track_open_loop",
    "schedule_reminder",
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
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(trace_token)
        _CURRENT_USER_ID.reset(user_token)
        _CHAT_ALREADY_PERSISTED.reset(chat_token)
        _TURN_WRITE_SIGNATURES.reset(sig_token)


def _is_terminator(tool_name: str) -> bool:
    return bool(tool_name) and tool_name.endswith(TERMINATOR_TOOL_SUFFIXES)


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
    await trace_post_tool_hook(hook_input)

    return {}


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
