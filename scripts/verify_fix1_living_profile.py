"""Verification script for Fix 1 (LP narrative becomes time-anchor-free).

Runs the new synthesis prompts against a real user's data WITHOUT persisting
the result. Prints:

1. The new narrative (eyeball for time-anchored language)
2. The full structured profile dict (eyeball other fields)
3. The wrapped LP block as Donna would read it (confirm no `today:` or `watch:` line)
4. A 24h-diff simulation: synthesize twice with `now_local` shifted, confirm
   narrative stability across the time gap.

Usage:
    python scripts/verify_fix1_living_profile.py <user_id>

Defaults to Arnav's user_id from the failing trace if no arg given.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from backend.memory.retrieval.structured import call_structured
from backend.memory.synthesis.living_profile import (
    _MODEL,
    _build_context,
    _build_full_prompt,
    _FullProfile,
    _MIN_SIGNAL_FOR_FULL_RUN,
)
from backend.memory.user_facts.rendering import render_living_profile_block

DEFAULT_USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"  # Arnav, from failing trace

TIME_ANCHOR_PHRASES = (
    "today",
    "tonight",
    "this morning",
    "this afternoon",
    "this evening",
    "right now",
    "as of",
    "in 4 hours",
    "in 5 hours",
    "in 6 hours",
    "by tonight",
    "by this evening",
    "in the next few hours",
)


def _check_for_time_anchors(text: str) -> list[str]:
    """Return a list of time-anchor phrases found in the text. Empty if clean."""
    low = text.lower()
    return [phrase for phrase in TIME_ANCHOR_PHRASES if phrase in low]


def _now_local_iso(tz_name: str, *, offset_hours: int = 0) -> str:
    """Build an ISO 'now_local' string, optionally shifted by offset_hours."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz) + timedelta(hours=offset_hours)
    return now.isoformat(timespec="minutes")


async def _synthesize_no_persist(user_id: str, *, offset_hours: int = 0) -> dict | None:
    """Run synthesis end-to-end but skip the DB write. Returns the profile dict."""
    ctx = await _build_context(user_id)
    if ctx is None:
        print(f"!! user {user_id[:8]} not found")
        return None
    if ctx.total_signal() < _MIN_SIGNAL_FOR_FULL_RUN:
        print(
            f"!! thin signal for user {user_id[:8]} "
            f"({ctx.total_signal()} < {_MIN_SIGNAL_FOR_FULL_RUN})"
        )
        return None

    now_local = _now_local_iso(ctx.timezone_name, offset_hours=offset_hours)
    print(f"   synthesizing with now_local={now_local}")
    prompt = _build_full_prompt(ctx, now_local=now_local)
    profile = await call_structured(
        model=_MODEL,
        system_prompt=prompt,
        user_message="Synthesize.",
        schema=_FullProfile,
        max_tokens=1400,
        timeout=45.0,
    )
    if profile is None:
        print(f"!! LLM returned None for user {user_id[:8]}")
        return None
    return profile.model_dump()


async def main() -> None:
    user_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_USER_ID
    print(f"=== Fix 1 verification for user {user_id[:8]} ===\n")

    print(">>> Step 1: Synthesize at now")
    profile_now = await _synthesize_no_persist(user_id)
    if profile_now is None:
        sys.exit(1)

    narrative_now = profile_now.get("narrative", "")
    print("\n--- narrative (now) ---")
    print(narrative_now)
    print(f"\n--- length: {len(narrative_now)} chars ---")

    leaks = _check_for_time_anchors(narrative_now)
    if leaks:
        print(f"\n!! TIME-ANCHOR LEAKS in narrative: {leaks}")
    else:
        print("\nOK no time-anchor phrases in narrative")

    # Also check today_shape and other rendered fields if present
    print("\n--- other fields ---")
    print(f"running_themes: {profile_now.get('running_themes')}")
    print(f"emotional_temperature: {profile_now.get('emotional_temperature')}")
    print(f"current_situation: {profile_now.get('current_situation')}")

    print("\n\n>>> Step 2: Render the wrapped LP block")
    block = render_living_profile_block(profile_now)
    print("--- rendered LIVING PROFILE block ---")
    print(block)
    print("--- end block ---")

    if "today:" in block:
        print("\n!! 'today:' line LEAKED into the rendered block")
    else:
        print("\nOK no 'today:' line in rendered block")
    if "watch:" in block:
        print("\n!! 'watch:' line LEAKED into the rendered block")
    else:
        print("\nOK no 'watch:' line in rendered block")

    print("\n\n>>> Step 3: 24h-diff simulation")
    print("    re-synthesizing with now_local shifted +24h to check stability...")
    profile_24h = await _synthesize_no_persist(user_id, offset_hours=24)
    if profile_24h is None:
        print("!! 24h synthesis failed")
        sys.exit(1)

    narrative_24h = profile_24h.get("narrative", "")
    print("\n--- narrative (24h shift) ---")
    print(narrative_24h)

    # Heuristic: narratives should be similar in shape if time-anchor-free.
    # We can't expect byte-equality (LLM noise) but the SUBSTANCE should track.
    leaks_24h = _check_for_time_anchors(narrative_24h)
    if leaks_24h:
        print(f"\n!! TIME-ANCHOR LEAKS in 24h narrative: {leaks_24h}")
    else:
        print("\nOK no time-anchor phrases in 24h narrative")

    # Save full output for inspection
    out_path = ROOT / "scripts" / "_out" / "verify_fix1_living_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "user_id": user_id,
                "now_synthesis": profile_now,
                "shift_24h_synthesis": profile_24h,
                "rendered_block": block,
                "leaks_now": leaks,
                "leaks_24h": leaks_24h,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nfull output written to {out_path.relative_to(ROOT)}")

    print("\n=== verification done ===")
    if leaks or leaks_24h or "today:" in block or "watch:" in block:
        print("FAIL: leaks detected, see above")
        sys.exit(1)
    print("PASS: no leaks, Fix 1 holds")


if __name__ == "__main__":
    asyncio.run(main())
