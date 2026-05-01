"""Estimate calories for a meal observation.

Two-tier strategy:
1. Lookup table for common food items (cheap, deterministic, fast).
2. Haiku fallback for unknown items (cached on the input string).

Returns ``(calories, confidence)`` where confidence is one of
``high|medium|low``. ``low`` means "we guessed; don't trust this for
nutritional counsel." Caller decides whether to ask the user for
clarification or accept the estimate.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]


# Lookup table — typical kcal for common dishes. Per-serving estimates,
# not per-100g. Numbers are approximations; the goal is "good enough for
# a daily-trend dashboard," not a clinical food log.
_LOOKUP: dict[str, int] = {
    # Indian
    "poha": 250,
    "banana": 100,
    "poha and banana": 350,
    "idli": 60,
    "dosa": 200,
    "masala dosa": 350,
    "paratha": 250,
    "roti": 100,
    "chapati": 100,
    "rice": 200,
    "jeera rice": 250,
    "biryani": 600,
    "chicken biryani": 700,
    "veg biryani": 550,
    "dal": 150,
    "dal rice": 350,
    "rajma": 200,
    "chole": 250,
    "paneer": 300,
    "samosa": 250,
    # Singapore / Chinese
    "chicken rice": 550,
    "hainanese chicken rice": 600,
    "scrambled egg rice": 450,
    "fried rice": 500,
    "chow mein": 450,
    "dim sum": 400,
    "laksa": 600,
    "char kway teow": 700,
    "wonton noodle": 400,
    "uttapam": 300,
    # Western
    "salad": 300,
    "caesar salad": 400,
    "burger": 600,
    "cheeseburger": 700,
    "pizza": 280,  # per slice
    "pizza slice": 280,
    "sandwich": 350,
    "pasta": 500,
    "spaghetti": 500,
    # Drinks (small but they add up)
    "coffee": 5,
    "latte": 120,
    "cappuccino": 80,
    "100 plus": 70,
    "coconut water": 45,
    "orange juice": 110,
    # Snacks / common
    "cookie": 150,
    "muffin": 350,
    "croissant": 250,
    "yogurt": 100,
    "fruit": 80,
    "apple": 80,
    "egg": 70,
    "boiled egg": 70,
    "scrambled egg": 90,
}


def _normalize(item: str) -> str:
    return re.sub(r"\s+", " ", item.strip().lower())


def _lookup_match(item: str) -> int | None:
    """Try exact, then substring, against the lookup table."""
    norm = _normalize(item)
    if not norm:
        return None
    if norm in _LOOKUP:
        return _LOOKUP[norm]
    # Substring: longest matching key wins (so "chicken rice" beats "rice").
    matches = [(k, v) for k, v in _LOOKUP.items() if k in norm or norm in k]
    if not matches:
        return None
    matches.sort(key=lambda kv: -len(kv[0]))
    return matches[0][1]


@lru_cache(maxsize=512)
def _haiku_estimate(item: str) -> int | None:
    """Ask Haiku for a per-serving kcal estimate. Cached on input string."""
    try:
        from anthropic import AsyncAnthropic
        import os
        import asyncio

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.debug("calorie_estimator: no API key; skipping Haiku")
            return None

        prompt = (
            "Estimate per-serving kcal for the following food item. "
            "Reply with a single integer between 0 and 2000, no units, no commentary. "
            f"If you can't estimate, reply with 0.\n\nItem: {item}"
        )

        async def _call() -> int | None:
            client = AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                getattr(b, "text", "") for b in resp.content if hasattr(b, "text")
            ).strip()
            m = re.search(r"\d+", text)
            if not m:
                return None
            n = int(m.group(0))
            return n if 0 < n <= 2000 else None

        return asyncio.run(_call())
    except Exception:
        logger.exception("calorie_estimator: Haiku call failed for %r", item)
        return None


def estimate_calories(item: str) -> tuple[int | None, Confidence]:
    """Estimate kcal for a meal item string.

    Returns ``(calories, confidence)``. ``calories`` is None when we can't
    estimate at all — caller should leave the field unset rather than
    fabricate a number.
    """
    if not item:
        return None, "low"
    table_hit = _lookup_match(item)
    if table_hit is not None:
        return table_hit, "high"
    haiku_hit = _haiku_estimate(item)
    if haiku_hit is not None:
        return haiku_hit, "medium"
    return None, "low"
