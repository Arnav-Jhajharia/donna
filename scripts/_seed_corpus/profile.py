"""Kai's static profile: identity, people, places, companies, TZ timeline.

All downstream generators consume these constants so the narrative stays
internally consistent (chat mentions line up with graph seeds, expense
merchants line up with places, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.memory.user_facts.schema import Confidence, FactKey, Source

# Stable identity — pinned so reruns clobber the same row.
SEED_USER_ID = "11111111-1111-4111-8111-111111111111"
SEED_PHONE = "+65seed0001"
SEED_NAME = "Kai"

CURRENT_TIMEZONE = "Asia/Singapore"
HOME_TIMEZONE = "America/Toronto"
TRIP_TIMEZONE = "America/New_York"

CURRENT_CITY = "Singapore"
HOME_CITY = "Toronto"
PROFESSION = "founder"

# Day offsets relative to anchor for the 3-day NY trip.
TRIP_START_OFFSET_DAYS = -15
TRIP_END_OFFSET_DAYS = -12

PEOPLE = {
    "maya": {"role": "cofounder", "company": "stripe_alumna"},
    "ravi": {"role": "cofounder", "company": "ex_shopify"},
    "saurabh": {"role": "investor_lead", "firm": "sequoia_sea"},
    "priya": {"role": "investor_angel", "firm": "independent"},
    "jess": {"role": "friend", "city": "singapore"},
    "tom": {"role": "friend", "city": "toronto"},
    "mom": {"role": "family", "city": "toronto"},
}

COMPANIES = {
    "stripe": "payments",
    "sequoia_sea": "vc",
    "anthropic": "ai_lab",
}

PLACES = {
    "singapore": ("SG", "Asia/Singapore"),
    "toronto": ("CA", "America/Toronto"),
    "new_york": ("US", "America/New_York"),
}


@dataclass(frozen=True)
class KaiProfileRow:
    """Shape of the seeded ``users`` row."""

    id: str
    phone: str
    name: str
    profession: str
    timezone: str
    wake_time: str
    sleep_time: str
    onboarding_complete: bool
    onboarding_goals: dict[str, Any]
    facts: dict[str, Any]
    is_sandbox: bool
    created_at: datetime
    last_active_at: datetime


def build_profile_row(anchor: datetime) -> KaiProfileRow:
    """Materialize the users row. ``facts`` use the UserFact TypedDict shape."""
    recorded_at = (anchor - timedelta(days=30)).isoformat()
    return KaiProfileRow(
        id=SEED_USER_ID,
        phone=SEED_PHONE,
        name=SEED_NAME,
        profession=PROFESSION,
        timezone=CURRENT_TIMEZONE,
        wake_time="06:30",
        sleep_time="23:30",
        onboarding_complete=True,
        onboarding_goals={"tz_done": True, "watch_done": True},
        facts={
            FactKey.PREFERRED_NAME.value: _fact(SEED_NAME, recorded_at),
            FactKey.CURRENT_CITY.value: _fact(CURRENT_CITY, recorded_at),
            FactKey.HOME_CITY.value: _fact(HOME_CITY, recorded_at),
            FactKey.CURRENT_TIMEZONE.value: _fact(CURRENT_TIMEZONE, recorded_at),
            FactKey.HOME_TIMEZONE.value: _fact(HOME_TIMEZONE, recorded_at),
            FactKey.PROFESSION.value: _fact(PROFESSION, recorded_at),
            FactKey.LIFE_STAGE.value: _fact("founder", recorded_at, confidence=Confidence.MEDIUM),
            FactKey.PRIMARY_LANGUAGE.value: _fact("english", recorded_at, confidence=Confidence.HIGH),
            FactKey.WAKE_TIME.value: _fact("06:30", recorded_at, confidence=Confidence.MEDIUM),
            FactKey.SLEEP_TIME.value: _fact("23:30", recorded_at, confidence=Confidence.MEDIUM),
        },
        is_sandbox=True,
        created_at=anchor - timedelta(days=30),
        last_active_at=anchor - timedelta(hours=1),
    )


def _fact(
    value: str,
    updated_at: str,
    *,
    source: Source = Source.ONBOARDING_EXPLICIT,
    confidence: Confidence = Confidence.HIGH,
) -> dict[str, str]:
    return {
        "value": value,
        "source": source.value,
        "confidence": confidence.value,
        "updated_at": updated_at,
    }


def timezone_for_offset(day_offset: int) -> str:
    """Return Kai's timezone on the given day offset (relative to anchor).

    He lives in SG, with a 3-day NY trip at offsets -15..-13.
    """
    if TRIP_START_OFFSET_DAYS <= day_offset <= TRIP_END_OFFSET_DAYS:
        return TRIP_TIMEZONE
    return CURRENT_TIMEZONE
