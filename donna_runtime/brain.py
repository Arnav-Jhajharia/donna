"""Donna brain — SDK tool-call loop bridging to the WhatsApp pipeline.

Runs the existing Claude Agent SDK tool-call loop (via `runner._donna_turn_core`)
for one inbound turn, captures messages emitted by the `send_burst` terminator
tool into `state["_outbound"]`, and returns the state.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from delivery.messages import TextMessage

from .config import DonnaAgentConfig, _stateless_sessions_default
from .context_builder import load_user_model_block, render_turn_context
from .hooks import _OUTBOUND_BUFFER
from .observability import emit_error, emit_retry_fired
from .runner import traced_donna_turn
from .session_store import resolve_session_id_db, save_user_session_db

logger = logging.getLogger(__name__)


async def donna_turn(state: dict, config: DonnaAgentConfig | None = None) -> dict:
    """Run one turn of the SDK brain. Mutates state with _outbound and returns it."""
    raw = (state.get("raw_input") or "").strip()
    user_id = state.get("user_id") or "unknown"
    logger.info("brain: turn for user=%s chars=%d", user_id[:8], len(raw))

    if not raw:
        state["_outbound"] = []
        return state

    cfg = config or DonnaAgentConfig()
    stateless = cfg.stateless_sessions or _stateless_sessions_default()
    if stateless:
        resume_id = None
    else:
        resume_id = await resolve_session_id_db(
            explicit_session_id=None,
            user_id=user_id,
        )
    state["_resume_session_id"] = resume_id

    # Deterministic pre-BRAIN fact detector — catches explicit corrections
    # ("my name is arnav btw not aayam") and writes to users.facts BEFORE
    # the USER MODEL block is rendered. No LLM call. The post-turn Haiku
    # extractor still runs for implicit mentions that don't match regex.
    try:
        from backend.memory.hooks import deterministic_fact_detector
        await deterministic_fact_detector.run(user_id, raw)
    except Exception:
        logger.exception("brain: deterministic fact detector failed (non-fatal)")

    turn_context = await render_turn_context(state)
    system_context = "\n\n".join(
        part for part in (cfg.system_context.strip(), turn_context.strip()) if part
    )
    user_model_block = await load_user_model_block(user_id)
    cfg = replace(
        cfg,
        user_id=user_id,
        resume_session_id=resume_id,
        fork_session=False,
        system_context=system_context,
        user_model_block=user_model_block,
        chat_already_persisted=True,
        user_phone=state.get("phone"),
        inbound_wa_message_id=state.get("platform_message_id"),
    )

    buffer: list = []
    token = _OUTBOUND_BUFFER.set(buffer)
    trace = None
    failed = False
    try:
        trace = await traced_donna_turn(raw, cfg)

        if resume_id and not trace.tool_calls and not buffer:
            logger.warning(
                "brain: resumed session %s produced zero tool calls for user=%s — retrying fresh",
                resume_id[:8], user_id[:8],
            )
            emit_retry_fired(
                kind="zero_tool_calls",
                reason="resumed session produced empty trace",
                source="brain",
            )
            buffer.clear()
            fresh_cfg = replace(cfg, resume_session_id=None, fork_session=False)
            trace = await traced_donna_turn(raw, fresh_cfg)
    except Exception as exc:
        logger.exception("brain: SDK loop failed for user=%s", user_id[:8])
        emit_error(where="brain.donna_turn", error=f"{type(exc).__name__}: {exc}")
        failed = True
    finally:
        _OUTBOUND_BUFFER.reset(token)

    if failed:
        # Reactive turns: ship a brief acknowledgment so the user knows we
        # heard them and a retry is implied. Proactive turns: stay silent.
        # The user wasn't expecting a message, so a fake "hm, one sec"
        # confuses them AND poisons RECENT CHAT (the model sees the row,
        # learns "this is what proactive looks like", and parrots it on
        # subsequent fires). The brand promise is reliability, not noise.
        if cfg.mode == "proactive":
            state["_outbound"] = []
        else:
            state["_outbound"] = [TextMessage(body="hm, one sec")]
        state["_brain_failed"] = True
        return state

    if trace.session_id and not stateless:
        try:
            await save_user_session_db(user_id, trace.session_id)
        except Exception:
            logger.exception("brain: save_user_session failed")

    try:
        trace.persist(cfg.trace_file)
    except Exception:
        logger.exception("brain: trace persist failed")

    state["_outbound"] = list(buffer)
    state["_turn_trace"] = trace
    return state
