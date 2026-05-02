"""One-off: call attend() with the hydration-watch intent and print the output.

This creates a real attention in the database — origin="donna", auto_live=True.
Cancel via the dashboard or list_attentions / cancel_attention if unwanted.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from donna_runtime.tools import _create_and_queue_attention

USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"  # Arnav

INTENT = (
    "if no water logged by 11am during a sprint window, "
    "surface one short hydration check — ONCE, not nagging"
)


async def main() -> None:
    print(f"calling attend(intent=..., origin='donna') for user {USER_ID[:8]}")
    print(f"intent: {INTENT!r}")
    print()

    result = await _create_and_queue_attention(
        intent=INTENT,
        user_id=USER_ID,
        origin="donna",
        label="attend_test",
    )

    print("=== raw result dict ===")
    print(json.dumps(result, indent=2, default=str))
    print()

    # Pull the attention back from the store to see what the author parsed.
    if result.get("status") in ("ok", "reused"):
        attention_id = result.get("attention_id")
        try:
            from donna.attention.store import AttentionStore

            store = AttentionStore()
            attention = await store.get(user_id=USER_ID, attention_id=attention_id)
            if attention is not None:
                print("=== parsed attention spec ===")
                print(json.dumps(attention.model_dump(), indent=2, default=str))
        except Exception as exc:
            print(f"!! could not fetch attention back: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
