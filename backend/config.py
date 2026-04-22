"""Backend settings — loaded from env, tolerant of missing values.

Clients/tools guarded by these settings should degrade gracefully (status: degraded)
when a required value is missing rather than crashing at import time.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    supermemory_api_key: str
    anthropic_api_key: str
    openai_api_key: str
    falkordb_host: str
    falkordb_port: int
    falkordb_username: str
    falkordb_password: str
    gate_log_path: str


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_get(
            "DATABASE_URL", "postgresql+asyncpg://donna:donna@localhost:5432/donna"
        ),
        supermemory_api_key=_get("SUPERMEMORY_API_KEY"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        openai_api_key=_get("OPENAI_API_KEY"),
        falkordb_host=_get("FALKORDB_HOST", "localhost"),
        falkordb_port=int(_get("FALKORDB_PORT", "6379")),
        falkordb_username=_get("FALKORDB_USERNAME", ""),
        falkordb_password=_get("FALKORDB_PASSWORD", ""),
        gate_log_path=_get("DONNA_GATE_LOG", "donna_gate.jsonl"),
    )


def require(name: str, value: str) -> bool:
    """Returns True if value present, else logs warning and returns False."""
    if not value:
        logger.warning("backend.config: %s missing — dependent calls will return status=degraded", name)
        return False
    return True
