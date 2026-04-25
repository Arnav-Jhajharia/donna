"""Calendar entries — past and upcoming events for the stress test."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CalendarRow:
    user_id: str
    title: str
    start_time: datetime  # naive UTC
    end_time: datetime | None
    location: str | None
    category: str | None


def build_calendar_rows(user_id: str, anchor: datetime) -> list[CalendarRow]:
    """Return ~25 calendar entries spread across ±30 days from anchor."""
    rows: list[CalendarRow] = []

    # Past — 5 board syncs, 3 cofounder 1:1s, 2 investor meetings
    for week_offset in range(5):
        rows.append(
            CalendarRow(
                user_id=user_id,
                title="board sync",
                start_time=anchor - timedelta(days=7 * (week_offset + 1) - 2, hours=7),
                end_time=anchor - timedelta(days=7 * (week_offset + 1) - 2, hours=6),
                location="office",
                category="work",
            )
        )
    for week_offset in range(3):
        rows.append(
            CalendarRow(
                user_id=user_id,
                title="1:1 with maya",
                start_time=anchor - timedelta(days=7 * (week_offset + 1), hours=6),
                end_time=anchor - timedelta(days=7 * (week_offset + 1), hours=5),
                location="slack huddle",
                category="work",
            )
        )
    rows.extend(
        [
            CalendarRow(
                user_id=user_id,
                title="saurabh intro call",
                start_time=anchor - timedelta(days=22, hours=3),
                end_time=anchor - timedelta(days=22, hours=2),
                location="zoom",
                category="investor",
            ),
            CalendarRow(
                user_id=user_id,
                title="ny investor dinner",
                start_time=anchor - timedelta(days=16, hours=0),
                end_time=anchor - timedelta(days=16, hours=-2),
                location="ny",
                category="investor",
            ),
        ]
    )

    # Upcoming 7 days — 4 meetings including weekly 1:1
    rows.extend(
        [
            CalendarRow(
                user_id=user_id,
                title="board sync",
                start_time=anchor + timedelta(hours=6),
                end_time=anchor + timedelta(hours=7),
                location="office",
                category="work",
            ),
            CalendarRow(
                user_id=user_id,
                title="1:1 with maya",
                start_time=anchor + timedelta(days=2, hours=-1),
                end_time=anchor + timedelta(days=2, hours=0),
                location="slack huddle",
                category="work",
            ),
            CalendarRow(
                user_id=user_id,
                title="saurabh weekly update",
                start_time=anchor + timedelta(days=3, hours=2),
                end_time=anchor + timedelta(days=3, hours=3),
                location="zoom",
                category="investor",
            ),
            CalendarRow(
                user_id=user_id,
                title="dinner with jess",
                start_time=anchor + timedelta(days=5, hours=12),
                end_time=anchor + timedelta(days=5, hours=14),
                location="amoy st",
                category="personal",
            ),
        ]
    )

    # Upcoming 14-30 days — 3 events including a flight
    rows.extend(
        [
            CalendarRow(
                user_id=user_id,
                title="flight SIN-YYZ",
                start_time=anchor + timedelta(days=18, hours=15),
                end_time=anchor + timedelta(days=19, hours=13),
                location="changi",
                category="travel",
            ),
            CalendarRow(
                user_id=user_id,
                title="coffee with tom (toronto)",
                start_time=anchor + timedelta(days=20, hours=2),
                end_time=anchor + timedelta(days=20, hours=3),
                location="toronto",
                category="personal",
            ),
            CalendarRow(
                user_id=user_id,
                title="q3 kickoff",
                start_time=anchor + timedelta(days=26, hours=1),
                end_time=anchor + timedelta(days=26, hours=4),
                location="office",
                category="work",
            ),
        ]
    )

    rows.sort(key=lambda r: r.start_time)
    return rows
