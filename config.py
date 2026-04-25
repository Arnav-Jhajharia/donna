from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = ""
    database_url_direct: str = ""
    supermemory_api_key: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "aura-verify-token"
    relay_url: str = ""
    founder_phone: str = ""
    # Per-phone dev re-routing. When both are set, webhooks whose `from`
    # matches DEV_PHONE_NUMBERS (comma-separated, no `+`) are forwarded to
    # DEV_RELAY_URL while the rest still process on this instance. Lets a
    # single prod webhook URL serve both prod traffic and a developer's
    # local tunnel without flipping the Meta dashboard each session.
    dev_relay_url: str = ""
    dev_phone_numbers: str = ""

    # Audio: ElevenLabs TTS (outbound voice notes) + Deepgram STT (inbound).
    # When DONNA_VOICE_ENABLED is false the voice_response marker is stripped
    # and Donna falls back to text. Inbound voice notes still transcribe.
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "WAhoMTNdLdMoq1j3wf3I"
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    elevenlabs_voice_speed: float = 1.2                 # 0.7 (slowest) – 1.2 (fastest); 1.0 = default
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    donna_voice_enabled: bool = True
    donna_voice_max_chars: int = 600                    # hard cap per turn (cost + WA voice-note ux)

    # Composio: SDK-managed OAuth + webhook ingest for Google integrations.
    composio_api_key: str = ""
    composio_webhook_secret: str = ""


settings = Settings()
