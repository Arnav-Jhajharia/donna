"""Curated, safe per-city object descriptors for the Day 1 illustration.

Each descriptor is one *iconic, beloved, neutral* object that fits a tabletop
or windowsill scene. Hard rules to avoid producing something dangerous:

  - No religious or political imagery
  - No human figures or faces
  - No regional caricature ("colorful chaos", "exotic spices")
  - No sacred motifs (temples, churches, mosques) as default
  - Specific named objects only — never "Indian morning" or "Asian dinner"
  - Object-scale, not landscape — we're filling the top half, not a billboard

Long-tail cities fall back to UNIVERSAL_DESCRIPTORS — warm, place-agnostic,
still feels personal because the user's name and city sit alongside.
"""
from __future__ import annotations

from typing import Literal

TimeBand = Literal["dawn", "morning", "midday", "evening", "late"]


# Per-city descriptors. Keep each line concrete and unambiguous so the model
# has no room to wander into stereotype. Curate carefully when adding cities.
CITY_DESCRIPTORS: dict[str, dict[TimeBand, str]] = {
    "singapore": {
        "dawn": "a small white ceramic cup of kopi with steam, on a marble countertop",
        "morning": "a white mug of kopi-c next to two slices of kaya toast on a small saucer",
        "midday": "a steaming bowl of laksa with chopsticks resting on top, simple ceramic bowl",
        "evening": "a tall glass of teh tarik with thick foam, condensation on the glass",
        "late": "a single small lamp glowing warm beside a closed leather notebook",
    },
    "mumbai": {
        "dawn": "a small steel kulhad of cutting chai on a wooden bench, faint steam",
        "morning": "a brass plate with two vada pav and a small chai glass",
        "midday": "a stainless steel thali with simple compartments of dal and rice, no people",
        "evening": "a glass of masala chai on a wooden table, ginger and cardamom beside it",
        "late": "a small clay diya glowing softly on a wooden surface",
    },
    "delhi": {
        "dawn": "a steel kulhad of chai on a wooden ledge, gentle steam",
        "morning": "a brass plate with one paratha and a small bowl of yogurt",
        "midday": "a steel tiffin opened to show simple home-style dal and rice",
        "evening": "a small glass of masala chai with ginger and a folded newspaper",
        "late": "a desk lamp casting warm light on a closed leather journal",
    },
    "bangalore": {
        "dawn": "a small steel tumbler of filter coffee with frothy top, on a wooden table",
        "morning": "a round plate with one masala dosa folded over, small bowl of chutney beside",
        "midday": "a banana leaf with neat compartments of rice and sambar, no people",
        "evening": "a glass of filter coffee with a folded book beside it",
        "late": "a small reading lamp on a wooden desk beside a closed notebook",
    },
    "new_york": {
        "dawn": "a paper coffee cup with a sleeve on a worn café counter",
        "morning": "a poppy-seed bagel sliced open on parchment paper, small tub of cream cheese",
        "midday": "a deli sandwich on butcher paper with a pickle wedge",
        "evening": "a tumbler of bourbon on a wooden bar with a folded napkin",
        "late": "a single brass desk lamp lit beside a closed Moleskine",
    },
    "san_francisco": {
        "dawn": "a small ceramic pour-over carafe with one cup beside it, on a wooden counter",
        "morning": "a flat white in a thick ceramic cup on a wooden cutting board",
        "midday": "a sourdough sandwich on a wooden board with a small green salad",
        "evening": "a tumbler of natural wine beside a closed paperback",
        "late": "a vintage desk lamp on a wooden table with a closed notebook",
    },
    "london": {
        "dawn": "a porcelain teacup of english breakfast on a saucer, faint steam",
        "morning": "a small porcelain teapot beside a single buttered toast on a plate",
        "midday": "a simple cheese-and-pickle sandwich on a wooden board",
        "evening": "a pint glass of amber ale on a worn wooden pub table",
        "late": "a green-shaded brass desk lamp beside a closed hardback book",
    },
    "paris": {
        "dawn": "a small espresso cup on a marble café table, sugar cube on the saucer",
        "morning": "a buttery croissant on a small white plate beside a café au lait",
        "midday": "half a baguette with a small wedge of cheese on a wooden board",
        "evening": "a glass of red wine on a marble table, folded newspaper underneath",
        "late": "a single candle in a small glass holder on a wooden surface",
    },
    "tokyo": {
        "dawn": "a small ceramic cup of green tea on a tatami-textured mat, faint steam",
        "morning": "a wooden bento box neatly compartmented with rice and pickled vegetables",
        "midday": "a simple bowl of ramen with chopsticks on top, single egg half visible",
        "evening": "a small ceramic sake cup beside a folded fan on a wooden surface",
        "late": "a small paper lantern glowing softly beside a closed book",
    },
    "seoul": {
        "dawn": "a small ceramic cup of barley tea on a stone coaster, faint steam",
        "morning": "a wooden tray with a bowl of rice and small banchan dishes",
        "midday": "a stone bowl of bibimbap with chopsticks resting on top",
        "evening": "a small ceramic cup of soju beside a closed notebook",
        "late": "a small ondol-style lamp glowing warm on a wooden floor",
    },
    "dubai": {
        "dawn": "a small glass of cardamom-spiced coffee with one date on a saucer",
        "morning": "a brass tray with a small cup of arabic coffee and dates beside",
        "midday": "a plate of warm flatbread with a small bowl of hummus",
        "evening": "a glass of mint lemonade with crushed ice on a metal table",
        "late": "a small brass lamp glowing warm on a dark wooden surface",
    },
    "sydney": {
        "dawn": "a small ceramic flat white on a wooden café counter, simple background",
        "morning": "a slice of avocado toast on a wooden board with a small flat white",
        "midday": "a simple poke bowl with chopsticks resting on top",
        "evening": "a glass of riesling on a wooden table beside a folded paperback",
        "late": "a small lamp lit beside a closed notebook on a wooden surface",
    },
    "toronto": {
        "dawn": "a paper cup of double-double coffee on a worn wooden counter",
        "morning": "a peameal bacon sandwich on a wooden board, small mug beside",
        "midday": "a hearty bowl of soup on a wooden table with crusty bread",
        "evening": "a tumbler of whiskey beside a closed hardback book",
        "late": "a single brass lamp glowing warm beside a closed journal",
    },
    "berlin": {
        "dawn": "a small espresso on a wooden café counter, simple background",
        "morning": "a slice of dark rye bread with butter and a small coffee cup",
        "midday": "a simple sandwich on parchment beside a glass of sparkling water",
        "evening": "a tall glass of beer on a worn wooden table",
        "late": "a single candle on a concrete tabletop, warm glow",
    },
}


# Universal fallback when the city isn't in the curated list. Still warm,
# still feels personal because the user's name and city sit alongside.
UNIVERSAL_DESCRIPTORS: dict[TimeBand, str] = {
    "dawn": "a small ceramic mug of coffee with rising steam, on a wooden table",
    "morning": "a white ceramic mug of coffee beside a folded napkin on a wooden surface",
    "midday": "a simple sandwich on a wooden board with a glass of water beside",
    "evening": "a single closed notebook on a wooden table beside a small glass",
    "late": "a small brass lamp glowing warm beside a closed book on wood",
}


def descriptor_for(city: str | None, time_band: TimeBand) -> str:
    """Resolve the safe object descriptor for this city + time-of-day.

    Falls back to UNIVERSAL_DESCRIPTORS when the city is unknown — never
    invents a free-form descriptor for an unknown place.
    """
    key = _normalize_city(city)
    if key and key in CITY_DESCRIPTORS:
        return CITY_DESCRIPTORS[key][time_band]
    return UNIVERSAL_DESCRIPTORS[time_band]


def has_curated_city(city: str | None) -> bool:
    return _normalize_city(city) in CITY_DESCRIPTORS


def _normalize_city(city: str | None) -> str:
    if not city:
        return ""
    return city.strip().lower().replace(" ", "_").replace("-", "_")
