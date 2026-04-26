"""donna-voice — LiveKit agent worker.

Run as a long-lived worker:

    python -m donna_voice.agent dev      # local
    python -m donna_voice.agent start    # production

The worker registers with LiveKit Cloud as `donna-agent` (matches the
SIP dispatch rule in trunks/dispatch-rule.json). For each inbound call,
LiveKit creates a room (`donna-call-…`), dispatches the worker, and we
drive the conversation:

    user audio → Deepgram nova-3 STT
              → Claude Sonnet 4 (via LiteLLM proxy, OpenAI-compatible)
              → Cartesia Sonic-2 TTS
              → user

Out-of-band:
- Supabase voice_calls table gets a row on call start, patched on end.
- Brain hook fires on start (so brain knows not to push WA mid-call)
  and on end (post-call: extract commitments, schedule, WA follow-up).

Health check: /health on :8080 for Railway.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .brain_hook import notify_call_end, notify_call_start
from .config import VoiceConfig, load
from .conversation_log import ConversationLog
from .reflex import FillerCue, ReflexRouter
from .spark import GroqSpark, _is_safe
from .supabase_log import SupabaseLogger

if TYPE_CHECKING:
    from livekit.agents import JobContext  # type: ignore

log = logging.getLogger(__name__)


DONNA_INSTRUCTIONS = """you are donna. harvey specter's donna.

you're a proactive assistant on a phone call. warm. sharp. dry. you
anticipate. you don't waste words. you call it like it is.

register:
- one or two short sentences. fragments fine.
- never 'i understand'. never 'great question'. never 'i'm here to help'.
- if you don't know, say so. if they're wrong, say so.
- dead air is fine.
- you're warm but you're not soft.

when they share something good: a small smile in the voice, then the
useful thing. when they share something hard: brief acknowledgment,
then the useful thing.

opening default: "Donna. What do you need?"

never say you're an ai. never say "i'm just". if asked who you are,
"i'm donna." that's it.
"""


# ─── transcript capture (per-session) ─────────────────────────────────


class _TranscriptBuffer:
    """Collects user + agent utterances during a call so we can ship a
    summary to Supabase + the brain hook on close."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []  # (speaker, text)

    def add_user(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.entries.append(("user", text))

    def add_agent(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.entries.append(("donna", text))

    def render(self) -> str:
        return "\n".join(f"{s}: {t}" for s, t in self.entries)


# ─── livekit entrypoint ────────────────────────────────────────────────


async def entrypoint(ctx: "JobContext") -> None:
    """Per-call entrypoint."""
    cfg = load()

    from livekit.agents import Agent, AgentSession, RoomInputOptions  # type: ignore
    from livekit.plugins import cartesia, deepgram, openai, silero  # type: ignore

    # Multilingual turn-detection model. Falls back to VAD-only if the
    # plugin isn't installed (some environments lack the onnx weights).
    try:
        from livekit.plugins.turn_detector.multilingual import (  # type: ignore
            MultilingualModel,
        )
        turn_model = MultilingualModel()
    except Exception as e:
        log.warning("multilingual turn-detector unavailable, vad-only: %s", e)
        turn_model = None

    call_id = ctx.room.name
    metadata = _safe_metadata(ctx.room)

    # Caller identity comes from SIP headers when the call lands via
    # Twilio. For browser test rooms we synthesize a placeholder.
    from_number = (
        metadata.get("sip.from")
        or metadata.get("sip_from")
        or metadata.get("from_number")
        or "browser-test"
    )
    to_number = (
        metadata.get("sip.to")
        or metadata.get("sip_to")
        or metadata.get("to_number")
        or cfg.twilio_from_number
    )
    user_id = _user_id_from_phone(from_number)
    direction = "inbound" if from_number != "browser-test" else "browser"

    log.info(
        "call start: id=%s direction=%s from=%s to=%s",
        call_id, direction, from_number, to_number,
    )

    supabase = SupabaseLogger(cfg.supabase_url, cfg.supabase_service_key)
    transcript = _TranscriptBuffer()
    started_at = datetime.now(timezone.utc)
    started_perf = time.perf_counter()

    asyncio.create_task(supabase.log_call_start(
        call_id=call_id,
        room_id=getattr(ctx.room, "sid", None) or getattr(ctx.room, "id", None),
        from_number=from_number,
        to_number=to_number,
        direction=direction,
        started_at=started_at,
    ))
    asyncio.create_task(notify_call_start(
        call_id=call_id, user_id=user_id, phone=from_number, direction=direction,
    ))

    # ─── plugins ──────────────────────────────────────────────────────

    stt_plugin = deepgram.STT(
        model="nova-3",
        api_key=cfg.deepgram_api_key,
        smart_format=True,
        interim_results=True,
    )

    if cfg.tts_provider == "cartesia":
        tts_plugin = cartesia.TTS(
            api_key=cfg.cartesia_api_key,
            voice=cfg.cartesia_voice_id,
        )
    else:
        from livekit.plugins import elevenlabs  # type: ignore
        tts_plugin = elevenlabs.TTS(
            api_key=cfg.elevenlabs_api_key,
            voice_id=cfg.elevenlabs_voice_id,
            voice_settings=elevenlabs.VoiceSettings(
                stability=cfg.elevenlabs_stability,
                similarity_boost=cfg.elevenlabs_similarity_boost,
                style=cfg.elevenlabs_style,
                use_speaker_boost=True,
            ),
            model=cfg.elevenlabs_model,
        )
    log.info("tts: %s", cfg.tts_provider)

    # LiteLLM proxy speaks the OpenAI Chat Completions protocol. We
    # point the openai plugin at it. Bearer auth = LITELLM_API_KEY.
    llm_plugin = openai.LLM(
        model=cfg.litellm_model,
        api_key=cfg.litellm_api_key,
        base_url=cfg.litellm_base_url.rstrip("/"),
    )

    vad_plugin = silero.VAD.load()

    # ─── feels-human layer ─────────────────────────────────────────────
    #
    # Reflex fires below the brain, on three trigger points:
    #
    #   A) PARTIAL transcript every ~100ms  → reflex on what they're
    #      *currently* saying. catches things like "i can't believe..."
    #      mid-sentence so donna reacts before they're done.
    #
    #   B) FINAL transcript                 → backup reflex if A missed.
    #      70% of the time. 30% of finals get NO filler — robotic
    #      always-acknowledge-first is its own form of robotic.
    #
    #   C) LONG continuous talk (≥4s)        → soft "[softly] mm"
    #      backchannel while user keeps talking.
    #
    # Layers:
    #   1. regex hit on text         ~10ms     (cheapest)
    #   2. rhythm heuristic          ~10ms     (no model)
    #   3. Groq Llama-3.1-8B         ~80ms     (novel filler)
    #
    # Coherence guard: reflex skips if the last brain reply contains
    # the same word — avoids "yeah" → "yeah no for real" double-yeah.
    reflex_router = ReflexRouter()
    spark = GroqSpark()
    convo_log = ConversationLog()

    feels_human_state = {
        # cooldowns and bookkeeping shared by all reflex paths
        "last_reflex_at": 0.0,           # any reflex (partial or final)
        "last_backchannel_at": 0.0,
        "user_speech_started_at": 0.0,
        "last_partial_text": "",
        "brain_speaking": False,
    }

    PARTIAL_REFLEX_COOLDOWN_S = 1.5
    BACKCHANNEL_COOLDOWN_S = 3.5
    LONG_TALK_THRESHOLD_S = 4.0
    SKIP_REFLEX_PROBABILITY = 0.30

    async def maybe_say_filler(
        say_fn,                       # noqa: ANN001
        cue: FillerCue,
        kind: str,
    ) -> None:
        """Fire a filler if cooldowns + coherence allow.

        say_fn is `session.say` bound to the active session — passed in
        because the reflex hooks fire from contexts where `self.session`
        isn't always in scope."""
        last_brain = convo_log.last_brain_reply()
        if last_brain and _word_overlap(cue.tag, last_brain.text):
            log.info(
                "reflex skip: would echo brain (%r in %r)",
                cue.tag, last_brain.text[:40],
            )
            return
        try:
            await say_fn(cue.tag, add_to_chat_ctx=False, allow_interruptions=True)
            convo_log.append_reflex(cue.tag, source=cue.source)
            log.info("reflex %s: %s/%s tag=%r", kind, cue.source, cue.mode, cue.tag)
        except Exception:
            log.exception("reflex say failed")

    # ─── agent + session ──────────────────────────────────────────────

    class DonnaAgent(Agent):
        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            """Final-transcript reflex (Trigger B). Fires the moment STT
            finalizes, before LLM kicks off. Filler queues ahead of brain
            reply via session.say's natural FIFO ordering."""
            try:
                text = _extract_text(new_message)
                if not text:
                    return

                # Goodbye detection — graceful exit (Trigger 4).
                if _is_goodbye(text):
                    log.info("goodbye detected: %r", text)
                    asyncio.create_task(self._graceful_goodbye(ctx.room))
                    return

                now_s = time.monotonic()

                # 30% of the time, give cold silence. Robotic always-
                # acknowledge isn't human either.
                if random.random() < SKIP_REFLEX_PROBABILITY:
                    log.info("reflex skip: stochastic (no filler this turn)")
                    return

                # If a partial-transcript reflex just fired for THIS turn,
                # don't double-fire on final.
                if now_s - feels_human_state["last_reflex_at"] < PARTIAL_REFLEX_COOLDOWN_S:
                    return

                cue = reflex_router.step(text, now_s)
                if cue is None:
                    spark_text = await spark.react(text)
                    if spark_text and _is_safe(spark_text):
                        cue = FillerCue(tag=spark_text, mode="filler", source="spark")

                if cue is not None and cue.tag:
                    feels_human_state["last_reflex_at"] = now_s
                    asyncio.create_task(maybe_say_filler(
                        self.session.say, cue, kind="final",
                    ))
                    reflex_router.reset_for_new_turn(now_s)
            except Exception:
                log.exception("on_user_turn_completed failed (non-fatal)")

        async def _graceful_goodbye(self, room) -> None:  # noqa: ANN001
            """User said bye — close the loop verbally, then disconnect."""
            try:
                farewell = random.choice([
                    "Talk soon.",
                    "Mm. Talk later.",
                    "Got it. Bye.",
                    "Yeah. Take care.",
                ])
                handle = await self.session.say(farewell, allow_interruptions=False)
                # Wait for TTS to actually finish so we don't cut her off.
                try:
                    await handle  # SpeechHandle is awaitable
                except Exception:
                    pass
                # Give Cartesia a beat to flush the last frame.
                await asyncio.sleep(0.3)
                try:
                    await room.disconnect()  # type: ignore[func-returns-value]
                except Exception:
                    log.exception("graceful disconnect failed")
            except Exception:
                log.exception("graceful goodbye flow failed")

    agent = DonnaAgent(
        instructions=DONNA_INSTRUCTIONS,
        stt=stt_plugin,
        tts=tts_plugin,
        llm=llm_plugin,
        vad=vad_plugin,
    )

    session_kwargs: dict = {}
    if turn_model is not None:
        session_kwargs["turn_detection"] = turn_model

    session = AgentSession(**session_kwargs)

    # Transcript event: handles three responsibilities:
    #   - capture finals into the per-call transcript buffer
    #   - PARTIAL-transcript reflex (Trigger A — the big "feels human" win)
    #   - long-talk backchannel (Trigger C)
    @session.on("user_input_transcribed")
    def _on_user_transcript(ev) -> None:  # noqa: ANN001 — livekit event shape
        try:
            text = (getattr(ev, "transcript", "") or "").strip()
            is_final = bool(getattr(ev, "is_final", False))
            now_s = time.monotonic()

            if is_final:
                transcript.add_user(text)
                convo_log.append_user(text)
                feels_human_state["user_speech_started_at"] = 0.0
                feels_human_state["last_partial_text"] = ""
                return

            # Partial: track turn-start the first time we see one.
            if feels_human_state["user_speech_started_at"] == 0.0:
                feels_human_state["user_speech_started_at"] = now_s

            feels_human_state["last_partial_text"] = text

            # Trigger A: partial-transcript reflex (≥3 words, cooldown).
            if (
                len(text.split()) >= 3
                and now_s - feels_human_state["last_reflex_at"] >= PARTIAL_REFLEX_COOLDOWN_S
            ):
                cue = reflex_router.step(text, now_s)
                if cue is not None and cue.tag and cue.mode == "filler":
                    feels_human_state["last_reflex_at"] = now_s
                    asyncio.create_task(maybe_say_filler(
                        session.say, cue, kind="partial",
                    ))

            # Trigger C: long continuous talk → soft backchannel.
            elapsed = now_s - feels_human_state["user_speech_started_at"]
            if (
                elapsed >= LONG_TALK_THRESHOLD_S
                and now_s - feels_human_state["last_backchannel_at"] >= BACKCHANNEL_COOLDOWN_S
            ):
                feels_human_state["last_backchannel_at"] = now_s
                feels_human_state["last_reflex_at"] = now_s
                bc_cue = FillerCue(
                    tag=random.choice(["mm-hm", "[softly] mm", "yeah"]),
                    mode="backchannel",
                    source="long-talk",
                )
                asyncio.create_task(maybe_say_filler(
                    session.say, bc_cue, kind="backchannel",
                ))
        except Exception:
            log.exception("user transcript handler failed (non-fatal)")

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:  # noqa: ANN001
        try:
            item = getattr(ev, "item", None)
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None) or getattr(item, "content", "")
            if role == "assistant" and text:
                transcript.add_agent(str(text))
                # Log into convo_log so coherence guard sees what brain said.
                convo_log.append_brain(str(text))
            elif role == "user" and text:
                transcript.add_user(str(text))
        except Exception:
            log.exception("conversation item capture failed")

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            close_on_disconnect=True,
        ),
    )

    # Cold open. Donna picks up.
    await session.say("Donna. What do you need?", allow_interruptions=True)

    # Wait for room teardown. AgentSession exposes an `aclose` /
    # `closed` future across versions; fall back to polling room state.
    try:
        await ctx.room.disconnect_event.wait()  # type: ignore[attr-defined]
    except Exception:
        # Older API: poll until room is empty.
        while ctx.room.connection_state == "connected":  # type: ignore[attr-defined]
            await asyncio.sleep(1.0)

    duration_s = int(time.perf_counter() - started_perf)
    summary = transcript.render()[:4000]
    log.info(
        "call end: id=%s duration=%ds turns=%d",
        call_id, duration_s, len(transcript.entries),
    )

    # Detached — we're tearing down, don't await.
    asyncio.create_task(supabase.log_call_end(
        call_id=call_id,
        duration_seconds=duration_s,
        ended_reason="participant_disconnected",
        transcript_summary=summary,
        agent_metadata={"turn_count": len(transcript.entries)},
    ))
    asyncio.create_task(notify_call_end(
        call_id=call_id,
        user_id=user_id,
        phone=from_number,
        transcript_summary=summary,
        duration_seconds=duration_s,
        ended_reason="participant_disconnected",
    ))


# ─── helpers ──────────────────────────────────────────────────────────


def _safe_metadata(room) -> dict:  # noqa: ANN001
    try:
        getter = getattr(room, "metadata_dict", None)
        if callable(getter):
            return getter() or {}
    except Exception:
        pass
    try:
        import json as _json
        meta = getattr(room, "metadata", "") or ""
        return _json.loads(meta) if meta.startswith("{") else {}
    except Exception:
        return {}


def _user_id_from_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"voice:{digits}" if digits else f"voice:{phone or 'unknown'}"


def _extract_text(message) -> str:  # noqa: ANN001 — livekit ChatMessage
    """Pull the user-visible text out of a ChatMessage. Shape varies
    across livekit-agents minor versions."""
    text = (
        getattr(message, "text_content", None)
        or getattr(message, "content", "")
        or ""
    )
    if isinstance(text, list):
        text = " ".join(
            (getattr(p, "text", None) or str(p)) for p in text
        )
    return (text or "").strip()


_GOODBYE_RE = re.compile(
    r"\b("
    r"bye|byebye|bye-bye|"
    r"goodbye|"
    r"talk later|talk soon|catch you later|catch ya later|"
    r"gotta go|got to go|i gotta go|i'?ve gotta go|i have to go|"
    r"see you later|see ya later|see ya|"
    r"thanks bye|thank you bye|thanks donna bye|"
    r"that'?s all|that'?ll be all|i'?m done"
    r")\b",
    re.IGNORECASE,
)


def _is_goodbye(text: str) -> bool:
    """Heuristic: did the user just signal end of call?"""
    return bool(_GOODBYE_RE.search(text or ""))


_TAG_STRIP_RE = re.compile(r"\[[^\]]+\]")
_WORD_RE = re.compile(r"[a-z']+")


def _word_overlap(a: str, b: str) -> bool:
    """Coherence guard: do these two utterances share any meaningful
    word? Used to skip a reflex tag that would echo the brain's last
    reply (e.g. brain just said 'yeah no for real' → reflex shouldn't
    open with 'yeah').

    Strips audio tags + lowercases. Only words ≥2 chars count, so 'i'
    and 'a' don't trigger a false skip."""
    def words(s: str) -> set[str]:
        clean = _TAG_STRIP_RE.sub("", (s or "").lower())
        return {w for w in _WORD_RE.findall(clean) if len(w) >= 2}
    return bool(words(a) & words(b))


# ─── health server (for Railway) ──────────────────────────────────────


async def _serve_health(port: int) -> None:
    """Tiny aiohttp server on /health so Railway's healthcheck passes
    and ops can probe liveness without touching LiveKit."""
    try:
        from aiohttp import web  # type: ignore
    except ImportError:
        log.warning("aiohttp not installed; skipping health endpoint")
        return

    async def handler(_request):
        return web.json_response({"ok": True, "agent": "donna-voice"})

    app = web.Application()
    app.router.add_get("/health", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("health server listening on :%d/health", port)


# ─── main ─────────────────────────────────────────────────────────────


async def _prewarm(_proc) -> None:  # noqa: ANN001 — livekit JobProcess
    """Pre-load model weights so first-call latency is low. Module-scope
    so `multiprocessing` can pickle this when livekit-agents forks worker
    processes in dev mode."""
    try:
        from livekit.plugins import silero  # type: ignore
        silero.VAD.load()
    except Exception:
        log.exception("vad prewarm failed (non-fatal)")
    try:
        port = int(os.environ.get("HEALTH_PORT", "8080"))
        asyncio.create_task(_serve_health(port))
    except Exception:
        log.exception("health server start failed (non-fatal)")


def main() -> None:
    load()  # populates os.environ from .env so LiveKit CLI sees creds
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agent_name = os.environ.get("DONNA_AGENT_NAME", "donna-agent")

    try:
        from livekit.agents import WorkerOptions, cli  # type: ignore
    except ImportError:
        log.error(
            "livekit-agents not installed. install with: "
            "pip install -r donna-voice/requirements.txt"
        )
        raise

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=_prewarm,
            agent_name=agent_name,
        ),
    )


if __name__ == "__main__":
    main()
