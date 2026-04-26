"""Runtime configuration for donna-voice.

Pulls every setting from env. Required vars fail fast on import; optional
vars fall back to defaults. Loads a sibling .env file when present so
local dev doesn't need a wrapper script.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def _load_env_file() -> None:
    """Load donna-voice/.env or repo-root .env (in that order) without
    overwriting variables already set in the process environment."""
    here = Path(__file__).resolve().parent
    candidates = [here / ".env", here.parent / ".env"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
                if key and key not in os.environ:
                    os.environ[key] = value
            log.info("loaded env from %s", path)
            return
        except Exception as e:
            log.warning("env file %s unreadable: %s", path, e)


def _req(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"required env var missing: {name}")
    return val


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class VoiceConfig:
    # LiveKit Cloud
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # STT
    deepgram_api_key: str

    # TTS provider — Cartesia preferred, ElevenLabs fallback
    tts_provider: str  # "cartesia" | "elevenlabs"
    cartesia_api_key: str
    cartesia_voice_id: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    elevenlabs_stability: float
    elevenlabs_similarity_boost: float
    elevenlabs_style: float

    # LLM via LiteLLM proxy (or any OpenAI-compatible endpoint)
    litellm_base_url: str
    litellm_api_key: str
    litellm_model: str

    # Supabase logging (optional — empty string disables)
    supabase_url: str
    supabase_service_key: str

    # Twilio outbound trunk (only used by the setup script)
    twilio_sip_password: str
    twilio_from_number: str

    # Agent identity (matches dispatch rule)
    agent_name: str = "donna-agent"

    # Health endpoint port
    health_port: int = 8080


def load() -> VoiceConfig:
    _load_env_file()

    # TTS provider — Cartesia preferred, ElevenLabs fallback. We auto-
    # detect based on which key is present so the same .env powers both
    # production (Cartesia) and dogfood (ElevenLabs already in donna repo).
    cartesia_key = _opt("CARTESIA_API_KEY")
    elevenlabs_key = _opt("ELEVENLABS_API_KEY")
    forced = _opt("TTS_PROVIDER").lower().strip()
    if forced in ("cartesia", "elevenlabs"):
        tts_provider = forced
    elif cartesia_key:
        tts_provider = "cartesia"
    elif elevenlabs_key:
        tts_provider = "elevenlabs"
    else:
        raise RuntimeError(
            "no TTS key configured: set CARTESIA_API_KEY or ELEVENLABS_API_KEY"
        )

    # LLM target — LiteLLM proxy preferred. If unset and a local donna
    # API is reachable, fall back to /voice/chat/completions on this
    # repo's running uvicorn (lets us ship without LiteLLM today).
    litellm_url = _opt("LITELLM_BASE_URL")
    litellm_key = _opt("LITELLM_API_KEY")
    if not litellm_url:
        donna_api = _opt("DONNA_BRAIN_URL", "http://localhost:8000")
        litellm_url = donna_api.rstrip("/") + "/voice"
        litellm_key = _opt("VOICE_BRAIN_SECRET", "missing")
        log.info(
            "LITELLM_BASE_URL not set → falling back to donna brain at %s",
            litellm_url,
        )

    if not litellm_key:
        raise RuntimeError(
            "LITELLM_API_KEY (or VOICE_BRAIN_SECRET for donna fallback) required"
        )

    return VoiceConfig(
        livekit_url=_req("LIVEKIT_URL"),
        livekit_api_key=_req("LIVEKIT_API_KEY"),
        livekit_api_secret=_req("LIVEKIT_API_SECRET"),
        deepgram_api_key=_req("DEEPGRAM_API_KEY"),
        tts_provider=tts_provider,
        cartesia_api_key=cartesia_key,
        cartesia_voice_id=_opt("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091"),
        elevenlabs_api_key=elevenlabs_key,
        elevenlabs_voice_id=_opt("ELEVENLABS_VOICE_ID", "XB0fDUnXU5powFXDhCwa"),
        elevenlabs_model=_opt("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        elevenlabs_stability=float(_opt("ELEVENLABS_STABILITY", "0.30")),
        elevenlabs_similarity_boost=float(_opt("ELEVENLABS_SIMILARITY_BOOST", "0.85")),
        elevenlabs_style=float(_opt("ELEVENLABS_STYLE", "0.55")),
        litellm_base_url=litellm_url,
        litellm_api_key=litellm_key,
        litellm_model=_opt("LITELLM_MODEL", "donna-voice"),
        supabase_url=_opt("SUPABASE_URL"),
        supabase_service_key=_opt("SUPABASE_SERVICE_KEY"),
        twilio_sip_password=_opt("TWILIO_SIP_PASSWORD"),
        twilio_from_number=_opt("TWILIO_FROM_NUMBER", "+14154232657"),
        agent_name=_opt("DONNA_AGENT_NAME", "donna-agent"),
        health_port=int(_opt("HEALTH_PORT", "8080")),
    )
