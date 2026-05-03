"""City → IANA timezone detection from inbound text.

Used by brain.donna_turn to lock a user's timezone deterministically when
they say something like "Hi from Bangalore" or "I'm in NYC" — before
BRAIN gets a chance to call attend with a wrong-tz wall-clock time.

Conservative by design: only fires on strong locative phrases ("from X",
"i'm in X", "based in X", "live in X", "currently in X"). Bare "in X"
is intentionally NOT a trigger — too easy to false-positive on phrases
like "meeting in Paris next month."

Unknown cities return None and the caller falls through to the existing
phone-prefix guess. The table covers the largest ~50 cities by user
density; extend by editing _CITY_TO_TZ.
"""
from __future__ import annotations

import re

# Lowercase city → IANA timezone. Multi-word entries get matched
# before single-word entries (longest-first sort in the matcher).
_CITY_TO_TZ: dict[str, str] = {
    # India
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "bombay": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "calcutta": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "ahmedabad": "Asia/Kolkata",
    "jaipur": "Asia/Kolkata",
    "gurgaon": "Asia/Kolkata",
    "gurugram": "Asia/Kolkata",
    "noida": "Asia/Kolkata",
    # United States
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "washington dc": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "philadelphia": "America/New_York",
    "philly": "America/New_York",
    "chicago": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "austin": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    # United Kingdom / Ireland
    "london": "Europe/London",
    "manchester": "Europe/London",
    "edinburgh": "Europe/London",
    "dublin": "Europe/Dublin",
    # Europe
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam",
    "madrid": "Europe/Madrid",
    "barcelona": "Europe/Madrid",
    "rome": "Europe/Rome",
    "milan": "Europe/Rome",
    "zurich": "Europe/Zurich",
    "geneva": "Europe/Zurich",
    "vienna": "Europe/Vienna",
    "stockholm": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki",
    "warsaw": "Europe/Warsaw",
    "athens": "Europe/Athens",
    "lisbon": "Europe/Lisbon",
    "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul",
    # Asia
    "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong",
    "tokyo": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "taipei": "Asia/Taipei",
    "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "ho chi minh": "Asia/Ho_Chi_Minh",
    "hanoi": "Asia/Ho_Chi_Minh",
    # Middle East
    "dubai": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "doha": "Asia/Qatar",
    "riyadh": "Asia/Riyadh",
    "tel aviv": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem",
    # Australia / NZ
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",
    # Canada
    "toronto": "America/Toronto",
    "ottawa": "America/Toronto",
    "montreal": "America/Montreal",
    "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton",
    # Latin America
    "sao paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago",
    "bogota": "America/Bogota",
    "lima": "America/Lima",
    "mexico city": "America/Mexico_City",
    # Africa
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
}

# Strong locative triggers. Ordered roughly by frequency. Each pattern
# captures the candidate city name in group 1. We deliberately do NOT
# include bare "in <city>" — too noisy ("meeting in paris next month").
_TRIGGER_PATTERNS = [
    re.compile(r"\bfrom\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so)\b|$)", re.IGNORECASE),
    re.compile(r"\bi(?:'m|m|\s+am)\s+(?:currently\s+|right now\s+)?in\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so|right|now)\b|$)", re.IGNORECASE),
    re.compile(r"\bbased\s+(?:in|out\s+of)\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so)\b|$)", re.IGNORECASE),
    re.compile(r"\b(?:i\s+)?live\s+(?:in|at)\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so)\b|$)", re.IGNORECASE),
    re.compile(r"\bcurrently\s+(?:in|at)\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so)\b|$)", re.IGNORECASE),
    re.compile(r"\bwriting\s+from\s+([a-z][a-z\s]{1,40}?)(?:[,.!?\n]|\s+(?:and|but|though|so)\b|$)", re.IGNORECASE),
]

# Cities sorted longest-first so "new york" beats "york" and
# "kuala lumpur" beats "lumpur".
_CITIES_LONGEST_FIRST = sorted(_CITY_TO_TZ.keys(), key=lambda c: (-len(c), c))


def detect_city_tz(text: str) -> tuple[str, str] | None:
    """Find the strongest locative city signal in `text`.

    Returns a tuple `(city, iana_tz)` on a confident match, or None.

    Confident match = a known city name appears immediately after one
    of the locative trigger phrases ("from", "i'm in", "based in",
    etc.) and is recognized in `_CITY_TO_TZ`.
    """
    if not text or not text.strip():
        return None
    for pattern in _TRIGGER_PATTERNS:
        for match in pattern.finditer(text):
            candidate = (match.group(1) or "").strip().lower()
            if not candidate:
                continue
            # Try longest known city that the candidate STARTS with.
            # Handles "bangalore india" → "bangalore".
            for city in _CITIES_LONGEST_FIRST:
                if candidate == city or candidate.startswith(city + " "):
                    return city, _CITY_TO_TZ[city]
    return None
