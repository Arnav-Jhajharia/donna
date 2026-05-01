"""One-shot smoke that fires a real BRAIN turn carrying an image and
publishes the trace to LangSmith.

Usage:
    python scripts/langsmith_image_smoke.py [--image PATH] [--message TEXT]

Reads `.env` for LANGCHAIN_API_KEY / LANGCHAIN_TRACING_V2. Costs a few
cents in Sonnet 4.6 vision tokens. Prints the LangSmith run URL on
success.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from donna_runtime.env import load_dotenv

load_dotenv()

import os

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.langsmith_tracing import flush as langsmith_flush
from donna_runtime.runner import traced_donna_turn

_DEFAULT_IMAGE = Path("dashboard/project/uploads/pasted-1776513361311-0.png")


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")


async def _run(image_path: Path, message: str) -> None:
    raw = image_path.read_bytes()
    mime = _mime_for(image_path)
    print(f"[smoke] image: {image_path} ({len(raw):,} bytes, {mime})")
    print(f"[smoke] message: {message!r}")
    print(f"[smoke] LANGCHAIN_TRACING_V2={os.getenv('LANGCHAIN_TRACING_V2')!r}")
    print(f"[smoke] project={os.getenv('LANGCHAIN_PROJECT') or os.getenv('LANGSMITH_PROJECT') or 'default'}")

    cfg = DonnaAgentConfig(
        user_id=f"smoke-{int(time.time())}",
        langsmith_enabled=True,
        langsmith_tags=("donna", "image-smoke"),
        stateless_sessions=True,
    )

    t0 = time.time()
    # traced_donna_turn opens the LangSmith chain run with the multimodal
    # inputs we built in runner.py. The public donna_turn() path skips that
    # wrapper, which is why we call traced_donna_turn directly here — same
    # as brain.donna_turn does in production.
    trace = await traced_donna_turn(message, cfg, images=[(raw, mime)])
    langsmith_flush()
    dt = time.time() - t0

    print(f"[smoke] turn done in {dt:.1f}s — session={trace.session_id}")
    print(f"[smoke] result: {(trace.result_text or '')[:300]}")
    print(f"[smoke] tools called: {[c.get('tool') for c in (trace.tool_calls or [])][:5]}")
    print()
    print("Open LangSmith → look for the most recent 'donna.turn' chain run")
    print("with tag 'image-smoke'. The 'multimodal_content' input renders the")
    print("image inline next to the wrapped prompt.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=_DEFAULT_IMAGE)
    parser.add_argument("--message", default="what is in this image?")
    args = parser.parse_args()

    if not args.image.exists():
        print(f"image not found: {args.image}", file=sys.stderr)
        sys.exit(2)

    asyncio.run(_run(args.image, args.message))


if __name__ == "__main__":
    main()
