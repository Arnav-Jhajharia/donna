"""Structured observability event emitter.

Single JSONL event stream at `DONNA_OBS_LOG` (default `.donna/events.jsonl`).
Every interesting thing Donna does — turns, tool calls, memory ops, hook
decisions, retries, errors — emits one typed event here.

Tail live:
    tail -f .donna/events.jsonl | jq '.'

Filter by type:
    jq 'select(.event == "memory.op")' .donna/events.jsonl

Env:
    DONNA_OBS_LOG     — path (default .donna/events.jsonl)
    DONNA_OBS_STDOUT  — also mirror each line to stdout when "1"

Event types (schema_version = 1; keep stable — dashboards depend on shape):
    turn.start   — BRAIN turn entered
    turn.end     — BRAIN turn finished
    tool.call    — model invoked a tool (from PreToolUse)
    hook.deny    — PreToolUse denied (duplicate write / double terminator)
    memory.op    — memory backend call with duration + result summary
    retry.fired  — silent-exit retry or zero-tool-call retry
    error        — caught exception worth flagging

All events share: event, ts, turn_id, user_id, schema_version.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

_OBS_LOG_PATH = Path(os.getenv("DONNA_OBS_LOG", ".donna/events.jsonl"))
_OBS_STDOUT = os.getenv("DONNA_OBS_STDOUT", "0") == "1"
_OBS_DISABLED = os.getenv("DONNA_OBS_DISABLED", "0") == "1"

_CURRENT_TURN_ID: ContextVar[str | None] = ContextVar(
    "donna_obs_turn_id", default=None
)
_CURRENT_USER_ID: ContextVar[str | None] = ContextVar(
    "donna_obs_user_id", default=None
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def emit(event: str, **data: Any) -> None:
    """Emit one structured event. Never raises; observability failures
    must never break a user turn."""
    if _OBS_DISABLED:
        return
    payload: dict[str, Any] = {
        "event": event,
        "ts": _now_iso(),
        "turn_id": _CURRENT_TURN_ID.get(),
        "user_id": _CURRENT_USER_ID.get(),
        "schema_version": _SCHEMA_VERSION,
    }
    payload.update(data)
    try:
        line = json.dumps(payload, default=str)
    except Exception:
        logger.exception("observability.emit: serialization failed for %s", event)
        return
    if _OBS_STDOUT:
        try:
            print(line, flush=True)
        except Exception:
            pass
    try:
        _OBS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _OBS_LOG_PATH.open("a") as fh:
            fh.write(line + "\n")
    except Exception:
        logger.exception("observability.emit: write to %s failed", _OBS_LOG_PATH)


@contextmanager
def turn_span(turn_id: str, user_id: str | None) -> Iterator[None]:
    """Bind turn_id + user_id into the event context for the duration."""
    tok1 = _CURRENT_TURN_ID.set(turn_id)
    tok2 = _CURRENT_USER_ID.set(user_id)
    try:
        yield
    finally:
        _CURRENT_TURN_ID.reset(tok1)
        _CURRENT_USER_ID.reset(tok2)


def _extract_user_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if kwargs.get("user_id"):
        return kwargs["user_id"]
    if args and isinstance(args[0], str):
        return args[0]
    return None


def _arg_summary(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint kwargs: key names + sizes/types, not raw values.

    Memory content can be sensitive (user secrets, PII). We log enough to
    debug but not the payloads themselves.
    """
    summary: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key == "user_id":
            continue
        if isinstance(value, str):
            summary[key] = {"type": "str", "len": len(value)}
        elif isinstance(value, (list, tuple)):
            summary[key] = {"type": "list", "len": len(value)}
        elif isinstance(value, dict):
            summary[key] = {"type": "dict", "keys": list(value.keys())[:10]}
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        else:
            summary[key] = {"type": type(value).__name__}
    return summary


def _result_summary(result: Any) -> dict[str, Any]:
    if result is None:
        return {"kind": "none"}
    if isinstance(result, dict):
        return {
            "kind": "dict",
            "keys": list(result.keys())[:10],
            "ok": result.get("ok"),
            "count": len(result.get("items") or []) if "items" in result else None,
        }
    if isinstance(result, (list, tuple)):
        return {"kind": "list", "count": len(result)}
    return {"kind": type(result).__name__}


def instrument_memory_op(backend: str) -> Callable:
    """Decorator for async memory ops. Emits `memory.op` on entry+exit.

    Usage:
        @instrument_memory_op("graphiti")
        async def recall_graph(user_id: str, query: str, ...): ...
    """
    def _decorate(fn: Callable) -> Callable:
        op_name = fn.__name__

        @functools.wraps(fn)
        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.time()
            user_id = _extract_user_id(args, kwargs)
            arg_summary = _arg_summary(kwargs)
            try:
                result = await fn(*args, **kwargs)
                emit(
                    "memory.op",
                    backend=backend,
                    op=op_name,
                    op_user_id=user_id,
                    args=arg_summary,
                    duration_ms=int((time.time() - start) * 1000),
                    result=_result_summary(result),
                    ok=True,
                )
                return result
            except Exception as exc:
                emit(
                    "memory.op",
                    backend=backend,
                    op=op_name,
                    op_user_id=user_id,
                    args=arg_summary,
                    duration_ms=int((time.time() - start) * 1000),
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise

        return _wrapped

    return _decorate


def emit_turn_start(
    *,
    turn_id: str,
    user_id: str | None,
    user_message: str,
    resume_session_id: str | None,
    model: str | None,
    thinking_enabled: bool,
) -> None:
    emit(
        "turn.start",
        user_message_len=len(user_message or ""),
        user_message_preview=(user_message or "")[:160],
        resume_session_id=resume_session_id,
        model=model,
        thinking_enabled=thinking_enabled,
    )


def emit_turn_end(trace: Any) -> None:
    """Summary event synthesized from a TurnTrace at end-of-turn."""
    try:
        d = trace.to_dict()
    except Exception:
        logger.exception("observability.emit_turn_end: trace.to_dict() failed")
        return
    tool_names = [
        str(c.get("tool") or "").split("__")[-1]
        for c in d.get("tool_calls") or []
    ]
    last_tool = tool_names[-1] if tool_names else None
    emit(
        "turn.end",
        duration_ms=d.get("duration_ms"),
        num_turns=d.get("num_turns"),
        total_cost_usd=d.get("total_cost_usd"),
        tool_count=len(tool_names),
        tools=tool_names,
        terminal_tool=last_tool,
        terminal_ok=(last_tool == "send_burst"),
        cache_creation_input_tokens=d.get("cache_creation_input_tokens"),
        cache_read_input_tokens=d.get("cache_read_input_tokens"),
        session_id=d.get("session_id"),
        result_is_error=d.get("result_is_error"),
        runtime_error=d.get("runtime_error"),
    )


def emit_hook_deny(*, tool_name: str, reason: str, decision_kind: str) -> None:
    emit(
        "hook.deny",
        tool=tool_name,
        decision_kind=decision_kind,
        reason=reason,
    )


def emit_retry_fired(*, kind: str, reason: str, source: str) -> None:
    emit("retry.fired", kind=kind, reason=reason, source=source)


def emit_error(*, where: str, error: str, **context: Any) -> None:
    emit("error", where=where, error=error, **context)
