"""Generate a COMPOSIO_WEBHOOK_SECRET and write it to .env.

Idempotent: if the variable is already present in .env, prints the existing
value instead of overwriting. Use the printed value to populate Composio's
webhook configuration in the dashboard.
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_VAR = "COMPOSIO_WEBHOOK_SECRET"


def _read_existing() -> str | None:
    if not _ENV_PATH.exists():
        return None
    pattern = re.compile(rf"^{_VAR}=(.+)$", re.MULTILINE)
    m = pattern.search(_ENV_PATH.read_text())
    if not m:
        return None
    value = m.group(1).strip().strip('"').strip("'")
    return value or None


def _append(value: str) -> None:
    line = f"{_VAR}={value}\n"
    if not _ENV_PATH.exists():
        _ENV_PATH.write_text(line)
        return
    text = _ENV_PATH.read_text()
    if not text.endswith("\n"):
        text += "\n"
    _ENV_PATH.write_text(text + line)


def main() -> int:
    existing = _read_existing()
    if existing:
        print(f"{_VAR} already set in {_ENV_PATH}")
        print(f"value: {existing}")
        return 0

    value = secrets.token_hex(32)
    _append(value)
    print(f"wrote {_VAR} to {_ENV_PATH}")
    print(f"value: {value}")
    print()
    print("next:")
    print("  1. paste this value into composio's webhook secret field")
    print("  2. set the webhook url to <your-ngrok-https>/webhooks/composio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
