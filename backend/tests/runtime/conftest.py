from __future__ import annotations

from pathlib import Path

from donna_runtime.env import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # runtime/ → tests/ → backend/ → root
load_dotenv(_ROOT / ".env")
