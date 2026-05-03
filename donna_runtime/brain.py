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
    return state


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

_FIRST_MESSAGE_DASHBOARD = (
    "your dashboard is here: {url}\n"
    "it fills up as we go. link's good for 5 minutes."
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
    """Build the deterministic Day 1 opener — three bubbles in succession.

    Bubble 1 is the intro: who Donna is and what she does.
    Bubble 2 is the pitch: three concrete affordances the user can pick
    from, plus an "anything else" door so it doesn't feel rigid.
    Bubble 3 is the dashboard handoff: the canvas surface itself, with
    a one-liner so the user knows it'll fill up as they engage.

    Three bubbles, not one, so WhatsApp renders them in succession the
    way a real person introducing themselves would. The dashboard rides
    on Day 1 specifically because Day 1 is the holistic "this is what
    Donna does" moment; after Day 1, the link is reserved for earned
    moments only (loop closes, streak ticks, explicit user request).

    If link minting fails (env misconfigured, token subsystem down) we
    still send the intro + pitch — losing the dashboard handoff is
    recoverable, losing the welcome is not.
    """
    from .tools import mint_dashboard_url

    name = _first_name(full_name)
    bubbles = [
        TextMessage(body=_FIRST_MESSAGE_INTRO.format(name=name)),
        TextMessage(body=_FIRST_MESSAGE_PITCH),
    ]
    url = mint_dashboard_url(user_id, reason="first_message")
    if url:
        bubbles.append(TextMessage(body=_FIRST_MESSAGE_DASHBOARD.format(url=url)))
    return bubbles


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
