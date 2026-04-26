from __future__ import annotations

from pathlib import Path

from donna_runtime.env import load_dotenv


_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
