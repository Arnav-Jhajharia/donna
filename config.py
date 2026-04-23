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


settings = Settings()
