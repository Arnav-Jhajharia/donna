"""Tier 2 judge — cheap Haiku 4.5 ping/hold/drop classifier with draft.

Mirrors the structured-output pattern used by
``backend.memory.hooks.extract_user_facts``: an Anthropic tool-use call
that forces the model to emit a single ``JudgeOutput`` JSON object. The
result is parsed into a frozen ``JudgeResult``. Failures (timeout, parse
error, missing draft on ping) return ``JudgeResult`` with ``failed=True``
so the dispatcher can fall back to Tier 3 without branching on exceptions.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from proactive.events import ProactiveEvent, SpeechAct

logger = logging.getLogger(__name__)

JUDGE_MODEL = "claude-haiku-4-5-20251001"
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "judge_v1.md"
_MAX_TOKENS = 400
_TIMEOUT_SECONDS = 8.0


JudgeAction = Literal["ping", "hold", "drop"]
JudgeRegister = Literal["alert", "soft"]


@dataclass(frozen=True)
class JudgeResult:
    """Tier 2 verdict.

    ``failed=True`` is the dispatcher's signal to fall back to the full
    brain. ``raw_response`` carries the original tool-use payload (or
    error string) for telemetry / replay.
    """

    action: JudgeAction
    register: JudgeRegister | None
    draft: str | None
    tie_in: tuple[str, ...]
    needs_tools: bool
    reasoning: str
    raw_response: str
    failed: bool = False
    failure_reason: str | None = None
    # NEW (Phase 1) — Tier 2's optional channel + speech-act-reclassification hints.
    channel_hint: Literal["whatsapp", "dashboard", "digest", "hold"] | None = None
    reclassify_speech_act: SpeechAct | None = None


class JudgeOutput(BaseModel):
    """Pydantic schema bound to the Anthropic tool-use input.

    Note: pydantic emits a ``UserWarning`` because ``register`` shadows an
    attribute name on ``BaseModel``. Functionally harmless — the field
    serializes / validates correctly — and renaming would force a prompt
    schema change. We accept the warning.
    """

    action: Literal["ping", "hold", "drop"] = Field(
        description="Whether to ping the user, hold the note, or drop it."
    )
    register: Literal["alert", "soft"] | None = Field(
        default=None,
        description="Only set when action=ping. null otherwise.",
    )
    draft: str | None = Field(
        default=None,
        description=(
            "Donna's drafted message in her voice. Required when action "
            "is ping or hold. Must be null when action is drop."
        ),
    )
    tie_in: list[str] = Field(
        default_factory=list,
        description=(
            "Short references to user state the brain might weave into "
            "the draft (open loop labels, attention ids, person names)."
        ),
    )
    needs_tools: bool = Field(
        default=False,
        description=(
            "True when the judge wants the full brain to verify with a "
            "tool call before sending."
        ),
    )
    reasoning: str = Field(
        default="",
        description="One short sentence for telemetry.",
    )
    # NEW (Phase 1)
    channel_hint: Literal["whatsapp", "dashboard", "digest", "hold"] | None = Field(
        default=None,
        description=(
            "Tier 2's channel routing recommendation. Tier 3 may override."
        ),
    )
    reclassify_speech_act: Literal[
        "dont_forget", "heads_up", "i_noticed", "now_the_moment", "thought_youd_want"
    ] | None = Field(
        default=None,
        description=(
            "If Tier 2 disagrees with the source's speech_act tag, set "
            "this to the corrected act. Null otherwise."
        ),
    )


@dataclass(frozen=True)
class _JudgeInputs:
    """Materialized prompt inputs. Kept frozen so the same event always
    hashes to the same prompt — useful for the offline diff harness.
    """

    user_model: str
    today_block: str
    recent_chat: str
    event_block: str


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text()
    except Exception:
        # Defensive: judge prompt missing means we cannot run Tier 2 at
        # all. Return a minimal stub so the call still parses (the model
        # will likely emit a low-confidence drop, which the dispatcher
        # treats as a valid outcome).
        logger.exception("judge: prompt file missing at %s", _PROMPT_PATH)
        return (
            "You are donna's proactive judge. Output JSON: "
            "{action, register, draft, tie_in, needs_tools, reasoning}."
        )


async def _load_user_model_block(user_id: str) -> str:
    try:
        from donna_runtime.context_builder import load_user_model_block

        return await load_user_model_block(user_id) or ""
    except Exception:
        logger.exception("judge: load_user_model_block failed user=%s", user_id)
        return ""


async def _load_today_block(user_id: str) -> str:
    try:
        from donna_runtime.context_builder import load_today_block

        return await load_today_block(user_id) or ""
    except Exception:
        logger.exception("judge: load_today_block failed user=%s", user_id)
        return ""


async def _load_recent_chat(user_id: str, limit: int = 5) -> str:
    """Render the last ``limit`` chat messages for the prompt."""
    try:
        from sqlalchemy import select

        from db.models import ChatMessage
        from db.session import async_session

        async with async_session() as session:
            rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        if not rows:
            return ""
        lines = []
        for row in reversed(rows):
            role = getattr(row, "role", "?") or "?"
            content = (getattr(row, "content", "") or "").strip()
            if not content:
                continue
            lines.append(f"- {role}: {content[:180]}")
        return "\n".join(lines)
    except Exception:
        logger.exception("judge: recent chat fetch failed user=%s", user_id)
        return ""


def _format_event_block(event: ProactiveEvent) -> str:
    payload_lines: list[str] = []
    for key, value in event.payload.items():
        rendered = str(value or "").strip()
        if not rendered:
            continue
        # Cap individual payload values so an outsized body excerpt does
        # not blow the prompt budget.
        if len(rendered) > 600:
            rendered = rendered[:600] + " ... <truncated>"
        payload_lines.append(f"  {key}: {rendered}")
    payload_block = "\n".join(payload_lines) if payload_lines else "  (empty)"

    score = event.signals.get("score")
    signal_labels = event.signals.get("signals") or []
    signals_line = (
        f"  score: {score}\n  signals: {', '.join(signal_labels) or 'none'}"
    )

    return (
        "PROACTIVE EVENT\n"
        f"source: {event.source}\n"
        f"source_ref: {event.source_ref}\n"
        f"topic_key: {event.topic_key}\n"
        "payload:\n"
        f"{payload_block}\n"
        "signals:\n"
        f"{signals_line}"
    )


async def _gather_inputs(event: ProactiveEvent) -> _JudgeInputs:
    user_model = await _load_user_model_block(event.user_id)
    today_block = await _load_today_block(event.user_id)
    recent_chat = await _load_recent_chat(event.user_id)
    event_block = _format_event_block(event)
    return _JudgeInputs(
        user_model=user_model,
        today_block=today_block,
        recent_chat=recent_chat,
        event_block=event_block,
    )


def _build_user_message(inputs: _JudgeInputs) -> str:
    parts: list[str] = []
    if inputs.user_model:
        parts.append("## USER MODEL\n" + inputs.user_model)
    if inputs.today_block:
        parts.append(inputs.today_block)
    if inputs.recent_chat:
        parts.append("## RECENT CHAT\n" + inputs.recent_chat)
    parts.append("## " + inputs.event_block)
    parts.append("Decide: ping / hold / drop. Emit only the JSON.")
    return "\n\n".join(parts)


def _validate_output(output: JudgeOutput) -> tuple[bool, str | None]:
    """Confirm the model's output respects the schema's invariants.

    Returns ``(ok, failure_reason)``.
    """
    if output.action == "ping":
        if output.register is None:
            return False, "ping_missing_register"
        if not (output.draft or "").strip():
            return False, "ping_missing_draft"
    elif output.action == "hold":
        if not (output.draft or "").strip():
            return False, "hold_missing_draft"
    elif output.action == "drop":
        if (output.draft or "").strip():
            return False, "drop_with_draft"
    if output.action != "ping" and output.register is not None:
        return False, "register_without_ping"
    return True, None


def _failed(reason: str, raw: str = "") -> JudgeResult:
    return JudgeResult(
        action="drop",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response=raw,
        failed=True,
        failure_reason=reason,
    )


async def _call_haiku(
    *,
    system_prompt: str,
    user_message: str,
) -> tuple[JudgeOutput | None, str]:
    """Run the structured Haiku call. Returns ``(parsed, raw_string)``.

    On any failure ``parsed`` is None and ``raw_string`` carries the
    failure indicator the dispatcher logs.
    """
    import asyncio

    try:
        from backend.config import get_settings
    except Exception:
        logger.exception("judge: settings unavailable")
        return None, "settings_unavailable"

    settings = get_settings()
    if not getattr(settings, "anthropic_api_key", None):
        return None, "no_api_key"

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return None, "anthropic_missing"

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tool = {
        "name": "emit_judgement",
        "description": "Emit the proactive judgement.",
        "input_schema": JudgeOutput.model_json_schema(),
    }

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "emit_judgement"},
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return None, "timeout"
    except Exception as exc:
        logger.exception("judge: api call failed")
        return None, f"api_error:{exc!r}"

    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "emit_judgement":
            payload = block.input
            try:
                return JudgeOutput.model_validate(payload), json.dumps(payload)
            except Exception:
                logger.exception("judge: parse failed payload=%s", json.dumps(payload)[:200])
                return None, f"parse_error:{json.dumps(payload)[:200]}"
    return None, "no_tool_use"


async def judge_event(event: ProactiveEvent) -> JudgeResult:
    """Run Tier 2. Returns a ``JudgeResult`` — ``failed=True`` on any
    failure mode the dispatcher should escalate.
    """
    system_prompt = _load_prompt()
    inputs = await _gather_inputs(event)
    user_message = _build_user_message(inputs)

    parsed, raw = await _call_haiku(
        system_prompt=system_prompt,
        user_message=user_message,
    )
    if parsed is None:
        return _failed(reason=raw or "no_output", raw=raw)

    ok, failure_reason = _validate_output(parsed)
    if not ok:
        return _failed(reason=failure_reason or "schema_violation", raw=raw)

    return JudgeResult(
        action=parsed.action,
        register=parsed.register,
        draft=(parsed.draft or "").strip() or None,
        tie_in=tuple(parsed.tie_in or ()),
        needs_tools=bool(parsed.needs_tools),
        reasoning=(parsed.reasoning or "").strip(),
        raw_response=raw,
    )


# Re-exported for tests / introspection.
__all__ = (
    "JUDGE_MODEL",
    "JudgeAction",
    "JudgeOutput",
    "JudgeRegister",
    "JudgeResult",
    "judge_event",
)
