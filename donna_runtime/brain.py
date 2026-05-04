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
    images = _extract_inbound_images(state)
    logger.info(
        "brain: turn for user=%s chars=%d images=%d",
        user_id[:8], len(raw), len(images),
    )

    # An image-only message (sticker, photo with no caption) is still a real
    # turn — Donna should respond to what's in the image. Fall back to a
    # neutral placeholder so the wrapped prompt is non-empty.
    if not raw and images:
        raw = "[image]"

    if not raw:
        state["_outbound"] = []
        return state

    # Pre-BRAIN city → tz lock. If the inbound carries a strong locative
    # signal ("from Bangalore", "i'm in NYC") and the user's tz hasn't
    # been confirmed yet, set it deterministically. Fires before BRAIN
    # specifically so any reminder tool the model calls this turn writes
    # an accurate UTC fire_at — phone-prefix guesses are wrong for
    # travelers and the first reminder is the worst place to find out.
    await _maybe_lock_city_tz(state, raw=raw, user_id=user_id)

    # Day 1 first-message: skip BRAIN entirely. Donna pitches herself with a
    # locked opener so the welcome lands the same every time. Reliability is
    # the brand on Day 1, and the user shouldn't see the model warming up.
    if state.get("_is_first_message"):
        state["_outbound"] = _first_message_outbound(
            user_id=user_id,
            full_name=state.get("_user_name") or "",
        )
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
        trace = await traced_donna_turn(raw, cfg, images=images or None)

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
            trace = await traced_donna_turn(raw, fresh_cfg, images=images or None)
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

    # Phase 2.5 plumbing: in Tier 3 mirror mode, the dispatcher reads
    # state["_tier3_outcome"] to capture which terminator the model called.
    # Mirror discipline says Tier 3 must NEVER reach the user, so we also
    # force _outbound back to empty regardless of what the SDK loop produced.
    if cfg.mode == "proactive_tier3":
        state["_outbound"] = []
        state["_tier3_outcome"] = _extract_tier3_outcome(trace)

    return state


_TIER3_TERMINATORS = ("skip", "kill_attention", "reshape_attention", "send_burst")
_TIER3_TERMINATOR_TO_ACTION = {
    "send_burst": "ship",
    "skip": "skip",
    "kill_attention": "kill",
    "reshape_attention": "reshape",
}


def _strip_mcp_prefix(name: str) -> str:
    """Strip ``mcp__<server>__`` prefix from an SDK tool name."""
    if "__" in name:
        return name.rsplit("__", 1)[-1]
    return name


def _normalize_send_burst_messages(messages: list) -> list:
    """Tier 3 send_burst input uses {'type': 'text', 'text': ...} but the
    dispatcher reads messages[0].get('body'). Mirror text→body so the
    existing dispatcher reader picks up the draft."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        normalized = dict(m)
        if "body" not in normalized and "text" in normalized:
            normalized["body"] = normalized["text"]
        out.append(normalized)
    return out


def _extract_tier3_outcome(trace) -> dict | None:
    """Walk the trace's tool_calls in reverse, find the LAST terminator,
    and return ``{"action": <action>, ...inputs}`` in the shape the dispatcher
    reads. Returns None if no terminator was called."""
    if trace is None:
        return None
    for call in reversed(getattr(trace, "tool_calls", []) or []):
        raw_name = str(call.get("tool") or "")
        short = _strip_mcp_prefix(raw_name)
        if short not in _TIER3_TERMINATORS:
            continue
        action = _TIER3_TERMINATOR_TO_ACTION[short]
        inputs = dict(call.get("inputs") or {})
        if action == "ship":
            inputs["messages"] = _normalize_send_burst_messages(inputs.get("messages") or [])
        return {"action": action, **inputs}
    return None


_FIRST_MESSAGE_INTRO = (
    "hi {name}, i'm donna. "
    "i hold what you tell me, follow up when it matters, "
    "and don't let things slip."
)

_FIRST_MESSAGE_PITCH = (
    "tell me something that keeps slipping away, "
    "an email you want me to track, "
    "or a tracker you want me to start "
    "or anything else honestly. "
    "we'll go from there."
)


def _first_name(full_name: str) -> str:
    """Extract first token from a WhatsApp display name. Lowercase to match
    Donna's voice. Empty input falls back to 'there' so the opener still
    reads naturally."""
    token = (full_name or "").strip().split()
    if not token:
        return "there"
    return token[0].lower()


def _first_message_outbound(*, user_id: str, full_name: str) -> list:
    """Build the deterministic Day 1 opener — two bubbles in succession.

    Bubble 1 is the intro: who Donna is and what she does.
    Bubble 2 is the pitch: three concrete affordances plus an "anything
    else" door so it doesn't feel rigid.

    No dashboard link on Day 1, and no deterministic Day-2 handoff. The
    model decides — via prompt rules — when to send the dashboard CTA,
    anchored on something concrete the user just offloaded or after
    sustained silence post-onboarding. Sending it cold teaches the
    user that dashboard pings are noise.
    """
    del user_id  # unused; reserved for future per-user opener tweaks
    name = _first_name(full_name)
    return [
        TextMessage(body=_FIRST_MESSAGE_INTRO.format(name=name)),
        TextMessage(body=_FIRST_MESSAGE_PITCH),
    ]


async def _maybe_lock_city_tz(state: dict, *, raw: str, user_id: str) -> None:
    """Detect a city signal in the inbound and lock tz if matched.

    Skips when:
      - tz already confirmed (state["_tz_done"] is True)
      - user_id missing
      - no city detected in the inbound
      - set_timezone import fails or DB write fails (logged + swallowed)

    On success, mutates `state["_user_timezone"]` and `state["_tz_done"]`
    in place so the rest of this turn (context builder, reminder tools)
    sees the new tz immediately, without re-reading the User row.
    """
    if not user_id or user_id == "unknown":
        return
    if state.get("_tz_done") is True:
        return
    try:
        from .city_tz import detect_city_tz
    except Exception:
        logger.exception("brain: city_tz import failed")
        return
    match = detect_city_tz(raw)
    if not match:
        return
    city, tz = match
    try:
        from backend.memory.tools.set_timezone import set_timezone as _set_timezone
    except Exception:
        logger.exception("brain: set_timezone import failed")
        return
    try:
        result = await _set_timezone(
            user_id=user_id, timezone=tz, source=f"city_signal:{city}"
        )
    except Exception:
        logger.exception(
            "brain: city_tz lock failed user=%s city=%s tz=%s",
            user_id[:8], city, tz,
        )
        return
    status = result.get("status") if isinstance(result, dict) else None
    if status == "ok":
        # Update in-memory state so this turn's tools see the new tz.
        state["_user_timezone"] = tz
        state["_tz_done"] = True
        state["_tz_source"] = f"city_signal:{city}"
        logger.info(
            "brain: city_tz locked user=%s city=%s tz=%s",
            user_id[:8], city, tz,
        )


def _extract_inbound_images(state: dict) -> list[tuple[bytes, str]]:
    """Pull (bytes, mime) tuples for any image attachments on the inbound payload.

    Today only one image rides per WhatsApp message, but the runner accepts a
    list so multi-image platforms (web upload, future stacking) drop in.
    """
    payload = state.get("_ingress_payload")
    if payload is None:
        return []
    image = getattr(payload, "image", None)
    if image is None:
        return []
    raw = getattr(image, "file_bytes", None)
    if not raw:
        return []
    mime = getattr(image, "mime_type", None) or "image/jpeg"
    return [(raw, mime)]
