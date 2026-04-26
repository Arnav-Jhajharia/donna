"""Eyeball one fal.ai Day 1 illustration — single call, prints the URL.

Sanity-check before we add caching, dashboard wiring, or tests. Picks one
(city, time_band, weather) tuple, builds the prompt via the curated
descriptors, fires fal once, prints the CDN URL plus the exact prompt that
went over the wire so you can judge whether it's on-brand.

Requires ``FAL_KEY`` in env (or in ``.env``).

Examples:

    # Default — singapore morning, clear weather
    python scripts/try_illustration.py

    # A different city + time
    python scripts/try_illustration.py --city tokyo --time-band evening

    # Rain in london late
    python scripts/try_illustration.py --city london --time-band late --weather rain
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.illustration.cities import TimeBand, has_curated_city
from backend.illustration.generate import IllustrationError, generate
from backend.illustration.prompt import IllustrationRequest, Weather

logger = logging.getLogger("try_illustration")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", type=str, default="singapore", help="City key (e.g. singapore, tokyo, london).")
    parser.add_argument(
        "--time-band",
        type=str,
        default="morning",
        choices=list(get_args(TimeBand)),
        help="Time of day band.",
    )
    parser.add_argument(
        "--weather",
        type=str,
        default="clear",
        choices=list(get_args(Weather)),
        help="Weather condition.",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="fal client timeout (seconds).")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    request = IllustrationRequest(
        city=args.city,
        time_band=args.time_band,
        weather=args.weather,
    )

    curated = has_curated_city(args.city)
    print(f"city={args.city} curated={curated} time_band={args.time_band} weather={args.weather}")

    try:
        result = await generate(request, timeout_s=args.timeout)
    except IllustrationError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"prompt:    {result.arguments.prompt}")
    print(f"style:     {result.arguments.style}")
    print(f"size:      {result.arguments.image_size}")
    print(f"mime:      {result.mime_type}")
    print(f"fal_id:    {result.fal_request_id}")
    print()
    print(f"url: {result.url}")
    return 0


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.debug("python-dotenv not installed; relying on shell env")
    else:
        load_dotenv(ROOT / ".env")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
