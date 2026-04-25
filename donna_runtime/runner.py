from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock, query

from .config import DonnaAgentConfig
from .hooks import _OUTBOUND_BUFFER, drain_memory_hooks, trace_hook_context
from .langsmith_tracing import end_run, flush as langsmith_flush, trace_run, tracing_context
from .observability import (
    _CURRENT_TURN_ID,
    emit,
    emit_error,
    emit_turn_end,
    emit_turn_start,
    turn_span,
)
from .options import build_options
from .prompt import wrap_user_message_with_context
from .session_store import save_user_session
from .tool_logic import set_voice_filter_enabled
from .tracing import TurnTrace


async def donna_turn(user_message: str, config: DonnaAgentConfig | None = None) -> TurnTrace:
    config = config or DonnaAgentConfig()
    return await _donna_turn_core(user_message, config)


async def traced_donna_turn(user_message: str, config: DonnaAgentConfig) -> TurnTrace:
    inputs = {
        "user_message": user_message,
        "model": config.model,
        "max_turns": config.max_turns,
        "resume_session_id": config.resume_session_id,
        "fork_session": config.fork_session,
        "user_id": config.user_id,
    }
    with trace_run(
        "donna.turn",
        "chain",
        inputs=inputs,
        project_name=config.langsmith_project,
        tags=config.langsmith_tags,
        metadata={"component": "donna", "runtime": "claude-agent-sdk-query"},
    ) as run_tree:
        trace = await _donna_turn_core(user_message, config)
        end_run(run_tree, trace.to_langsmith_outputs())
        return trace


async def _donna_turn_core(user_message: str, config: DonnaAgentConfig) -> TurnTrace:
    set_voice_filter_enabled(config.voice_filter_enabled)
    trace = TurnTrace(user_message)
    trace.record_resume_session_id(config.resume_session_id)

    existing = _OUTBOUND_BUFFER.get()
    buffer: list = existing if existing is not None else []
    token = _OUTBOUND_BUFFER.set(buffer) if existing is None else None

    owns_turn_span = _CURRENT_TURN_ID.get() is None
    turn_id = f"turn_{int(time.time() * 1000)}" if owns_turn_span else None
    span_cm = turn_span(turn_id, config.user_id) if owns_turn_span else _nullspan()

    try:
        with span_cm:
            if owns_turn_span:
                emit_turn_start(
                    turn_id=turn_id,
                    user_id=config.user_id,
                    user_message=user_message,
                    resume_session_id=config.resume_session_id,
                    model=config.model,
                    thinking_enabled=bool(getattr(config, "thinking_enabled", False)),
                )
            with trace_hook_context(
                trace,
                user_id=config.user_id,
                chat_already_persisted=config.chat_already_persisted,
            ):
                try:
                    wrapped_prompt = wrap_user_message_with_context(
                        user_message, config.system_context
                    )
                    async with asyncio.timeout(config.request_timeout_s):
                        async for message in query(prompt=wrapped_prompt, options=build_options(config)):
                            _record_message(trace, message)
                except TimeoutError:
                    trace.record_runtime_error(f"Donna Agent SDK query timed out after {config.request_timeout_s:.1f}s")
                    emit_error(where="runner._donna_turn_core", error="sdk_query_timeout", timeout_s=config.request_timeout_s)
                except Exception as exc:
                    trace.record_runtime_error(str(exc))
                    emit_error(where="runner._donna_turn_core", error=f"{type(exc).__name__}: {exc}")
                    if not trace.session_id and not trace.result_text:
                        raise
            if owns_turn_span:
                emit_turn_end(trace)
    finally:
        if token is not None:
            _OUTBOUND_BUFFER.reset(token)

    if config.target_phone and buffer:
        await _deliver_to_whatsapp(config.target_phone, buffer)

    return trace


@contextmanager
def _nullspan():
    yield


def _emit_tool_call_event(block: ToolUseBlock) -> None:
    name = str(block.name or "")
    short = name.split("__")[-1] if name else ""
    inputs = block.input if isinstance(block.input, dict) else {}
    emit(
        "tool.call",
        tool=name,
        tool_short=short,
        call_id=str(block.id),
        input_keys=list(inputs.keys())[:20],
    )


async def _deliver_to_whatsapp(phone: str, messages: list) -> None:
    try:
        from delivery.whatsapp import WhatsAppChannel
        wa = WhatsAppChannel()
        wamids = await wa.send_many(phone, messages)
        logging.getLogger(__name__).info("runner: sent %d WA messages to %s (wamids=%s)", len(messages), phone[:6], wamids)
    except Exception:
        logging.getLogger(__name__).exception("runner: WA delivery failed for %s", phone[:6])


async def run_messages(
    messages: tuple[str, ...],
    config: DonnaAgentConfig | None = None,
    trace_file: Path | None = None,
) -> list[TurnTrace]:
    config = config or DonnaAgentConfig()
    target_trace_file = trace_file or config.trace_file
    traces: list[TurnTrace] = []

    with tracing_context(
        enabled=config.langsmith_enabled,
        project_name=config.langsmith_project,
        tags=config.langsmith_tags,
        metadata={"component": "donna", "message_count": len(messages), "user_id": config.user_id},
    ):
        current_config = config
        for message in messages:
            trace = await _run_turn_with_resume_fallback(message, current_config)
            trace.pretty_print()
            trace.persist(target_trace_file)
            traces.append(trace)
            if current_config.user_id and trace.session_id:
                save_user_session(current_config.session_store_file, current_config.user_id, trace.session_id)
            if trace.session_id:
                current_config = replace(
                    current_config,
                    resume_session_id=trace.session_id,
                    fork_session=False,
                )

    await drain_memory_hooks()

    if config.langsmith_enabled:
        langsmith_flush()

    print(f"\n\nAll traces written to: {target_trace_file.resolve()}")
    print(f"Inspect individual traces with: jq '.' {target_trace_file}")
    if traces and traces[-1].session_id:
        print(f"Latest Claude session id: {traces[-1].session_id}")
    return traces


async def _run_turn_with_resume_fallback(message: str, config: DonnaAgentConfig) -> TurnTrace:
    try:
        return await traced_donna_turn(message, config)
    except Exception as exc:
        if config.resume_session_id and _should_retry_without_resume(exc):
            fresh_config = replace(config, resume_session_id=None, fork_session=False)
            return await traced_donna_turn(message, fresh_config)
        raise


def _should_retry_without_resume(exc: Exception) -> bool:
    return _is_missing_resume_error(exc) or "command failed with exit code" in str(exc).lower()


def _is_missing_resume_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "no conversation found with session id" in text or "session not found" in text


def _record_message(trace: TurnTrace, message: Any) -> None:
    session_id = _extract_session_id(message)
    if session_id:
        trace.record_session_id(session_id)

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                trace.record_thought(block.text)
            elif isinstance(block, ToolUseBlock):
                trace.record_tool_call(
                    name=block.name,
                    inputs=block.input,
                    call_id=block.id,
                )
                _emit_tool_call_event(block)
    elif isinstance(message, ResultMessage):
        trace.record_result(
            subtype=getattr(message, "subtype", None),
            result=getattr(message, "result", None),
            is_error=getattr(message, "is_error", None),
        )
        trace.finalize(
            cost=getattr(message, "total_cost_usd", None) or 0.0,
            num_turns=getattr(message, "num_turns", None) or 0,
        )
        trace.record_usage(getattr(message, "usage", None))
    elif isinstance(message, SystemMessage):
        trace.record_session_id(session_id)


def _extract_session_id(message: Any) -> str | None:
    direct = getattr(message, "session_id", None)
    if direct:
        return str(direct)

    data = getattr(message, "data", None)
    if isinstance(data, dict) and data.get("session_id"):
        return str(data["session_id"])

    if isinstance(message, dict):
        if message.get("session_id"):
            return str(message["session_id"])
        nested = message.get("data")
        if isinstance(nested, dict) and nested.get("session_id"):
            return str(nested["session_id"])
    return None
