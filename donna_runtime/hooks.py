from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .langsmith_tracing import traceable
from .tracing import TurnTrace

logger = logging.getLogger(__name__)


_CURRENT_TRACE: ContextVar[TurnTrace | None] = ContextVar("donna_current_trace", default=None)
_CURRENT_USER_ID: ContextVar[str | None] = ContextVar("donna_current_user_id", default=None)
_OUTBOUND_BUFFER: ContextVar[list | None] = ContextVar("donna_outbound_buffer", default=None)

_PENDING_HOOK_TASKS: set[asyncio.Task] = set()


async def drain_memory_hooks() -> None:
    if not _PENDING_HOOK_TASKS:
        return
    await asyncio.gather(*list(_PENDING_HOOK_TASKS), return_exceptions=True)


@contextmanager
def trace_hook_context(trace: TurnTrace, user_id: str | None = None) -> Iterator[None]:
    trace_token = _CURRENT_TRACE.set(trace)
    user_token = _CURRENT_USER_ID.set(user_id)
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(trace_token)
        _CURRENT_USER_ID.reset(user_token)


async def pre_tool_hook(input_data, tool_use_id, context):
    trace = _CURRENT_TRACE.get()
    hook_input = _hook_payload(input_data, tool_use_id)
    if trace is not None:
        trace.record_hook_pre(hook_input, str(tool_use_id))
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
    tool_names = [c["tool"] for c in trace.tool_calls]
    ctx = {
        "user_id": user_id,
        "inbound": trace.user_message,
        "outbound": [str(m) for m in outbound],
        "tool_names": tool_names,
        "terminator": "send_burst",
        "user_facts": {},
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
