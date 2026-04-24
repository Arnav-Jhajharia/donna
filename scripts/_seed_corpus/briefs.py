"""Situation brief variants — three freshness levels for the stress test.

Per docs/memory-stress-test-plan.md Phase 2: "Generate three versions:
fresh (< 1h old), 3-day stale, 14-day stale. Stress the freshness axis."

The stored shape matches ``backend.memory.synthesis.temporal_brief.TemporalBrief``:
keys in users.living_profile["situation_brief"].
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class BriefVariant:
    """One freshness level of the stored situation brief."""

    name: str  # fresh | 3d_stale | 14d_stale
    staleness_hours: int
    payload: dict[str, Any]


def build_brief_variants(anchor: datetime) -> list[BriefVariant]:
    """Return three TemporalBrief-shaped payloads at different freshness ages."""
    return [
        _variant("fresh", 0, anchor),
        _variant("3d_stale", 24 * 3, anchor),
        _variant("14d_stale", 24 * 14, anchor),
    ]


def _variant(name: str, staleness_hours: int, anchor: datetime) -> BriefVariant:
    generated_at = (anchor - timedelta(hours=staleness_hours)).isoformat()
    # Evidence lines match the shape rendered by temporal_brief._format_item:
    #   "{YYYY-MM-DD HH:MM} {kind}[/{role}]: {text}"
    current_status = [
        f"{_iso_day(anchor, -1)} 09:30 observation:mood: anxious about fundraising, steady after talk with maya",
        f"{_iso_day(anchor, -1)} 15:00 schedule: board sync tomorrow 3pm SG",
        f"{_iso_day(anchor, -2)} 11:00 open_loop: finish board sync prep doc",
    ]
    this_week = [
        f"{_iso_day(anchor, -6)} 19:00 observation:meal: dinner with maya at amoy st japanese",
        f"{_iso_day(anchor, -3)} 11:00 schedule: set up saurabh weekly update cadence",
        f"{_iso_day(anchor, -2)} 20:00 chat/user: anxious about board sync friday",
    ]
    last_week = [
        f"{_iso_day(anchor, -15)} 10:00 chat/user: saurabh agreed to co-invest with priya, 12m pre",
        f"{_iso_day(anchor, -10)} 11:00 chat/user: priya wires 500k next week, clean",
        f"{_iso_day(anchor, -8)} 16:00 chat/user: maya closed infra migration 2 days ahead",
    ]
    next_week = [
        f"{_iso_day(anchor, 3)} 10:00 calendar: saurabh weekly update via zoom",
        f"{_iso_day(anchor, 5)} 20:00 calendar: dinner with jess amoy st",
    ]
    open_loops = [
        f"{_iso_day(anchor, -1)} open_loop: confirm dinner with maya",
        f"{_iso_day(anchor, -6)} open_loop: respond to saurabh term sheet",
        f"{_iso_day(anchor, -14)} open_loop: clarify hiring plan with maya",
        f"{_iso_day(anchor, -25)} open_loop: call mom this weekend",
    ]
    payload = {
        "implementation": "windowed_timeline",
        "generated_at": generated_at,
        "summary": (
            "kai is one day out from the board sync. fundraise is closing "
            "(saurabh 10m pre co-invest with priya 500k). maya is solid, "
            "ravi conflict resolved. open threads: confirm dinner with maya, "
            "term sheet response, hiring plan clarification."
        ),
        "current_status": current_status,
        "last_week": last_week,
        "this_week": this_week,
        "next_week": next_week,
        "open_loops": open_loops,
        "stale_or_uncertain": [
            f"{_iso_day(anchor, -25)} open_loop: call mom this weekend (25 days old)",
        ],
        "evidence_used": {
            "chat_messages": 42,
            "observations": 60,
            "open_loops": 8,
            "calendar": 17,
            "schedules": 0,
        },
    }
    return BriefVariant(name=name, staleness_hours=staleness_hours, payload=payload)


def _iso_day(anchor: datetime, offset_days: int) -> str:
    return (anchor + timedelta(days=offset_days)).strftime("%Y-%m-%d")
