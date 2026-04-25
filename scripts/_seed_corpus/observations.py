"""Observation generator: expenses, meals, mood, sleep, habits.

Counts match docs/memory-stress-test-plan.md Phase 2 targets:
expense=25, meal=18, mood=7, sleep=6, habit=4.

``fields`` keys are stable per type so the observations lane's aggregate
can bucket them without alias noise (see ``backend/memory/retrieval/fanout.py``).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class ObservationRow:
    user_id: str
    type: str
    event_time: datetime  # naive UTC
    tags: dict[str, Any]
    fields: dict[str, Any]
    raw: str


_MERCHANTS_SG = [
    ("grab", "SGD", (8, 18)),
    ("hawker amoy", "SGD", (5, 10)),
    ("starbucks", "SGD", (6, 9)),
    ("cold storage", "SGD", (20, 60)),
    ("wework", "SGD", (15, 25)),
    ("maxwell food", "SGD", (5, 12)),
]

_MERCHANTS_NY = [
    ("la colombe", "USD", (6, 9)),
    ("uber", "USD", (10, 25)),
    ("sweetgreen", "USD", (14, 20)),
    ("bowery hotel bar", "USD", (15, 30)),
]

_MEALS = [
    ("breakfast", ["oats", "eggs toast", "chia pudding", "kaya toast"]),
    ("lunch", ["hawker chicken rice", "mee pok", "sweetgreen salad", "curry puff"]),
    ("dinner", ["japanese izakaya", "ramen", "nasi lemak", "home cooked"]),
    ("snack", ["protein bar", "coffee bun", "iced coffee"]),
]

_MOOD_NOTES = [
    "anxious about fundraising",
    "steady after the talk with maya",
    "jetlagged",
    "clear headed",
    "frustrated with ravi",
    "good energy",
    "tired but okay",
]

_HABITS = [
    ("workout", "gym"),
    ("meditation", "headspace 10m"),
    ("reading", "inspired 30m"),
    ("run", "east coast 5k"),
]


def build_observation_rows(
    user_id: str,
    anchor: datetime,
    rng: random.Random,
) -> list[ObservationRow]:
    """Return the 60-row observation corpus for Kai. Order ascending by time."""
    rows: list[ObservationRow] = []
    rows.extend(_build_expenses(user_id, anchor, rng, count=25))
    rows.extend(_build_meals(user_id, anchor, rng, count=18))
    rows.extend(_build_moods(user_id, anchor, rng, count=7))
    rows.extend(_build_sleeps(user_id, anchor, rng, count=6))
    rows.extend(_build_habits(user_id, anchor, rng, count=4))
    rows.sort(key=lambda r: r.event_time)
    return rows


def _build_expenses(user_id: str, anchor: datetime, rng: random.Random, *, count: int) -> list[ObservationRow]:
    out: list[ObservationRow] = []
    for i in range(count):
        day_offset = rng.randint(-29, 0)
        in_ny_trip = -15 <= day_offset <= -13
        merchant, currency, amount_range = rng.choice(
            _MERCHANTS_NY if in_ny_trip else _MERCHANTS_SG
        )
        amount = round(rng.uniform(*amount_range), 2)
        local_hour = rng.choice([8, 12, 13, 18, 19, 20])
        jitter = rng.randint(0, 59)
        event_time = anchor + timedelta(
            days=day_offset, hours=local_hour - 8, minutes=jitter
        )
        out.append(
            ObservationRow(
                user_id=user_id,
                type="expense",
                event_time=event_time,
                tags={"merchant": merchant, "city": "new_york" if in_ny_trip else "singapore"},
                fields={"amount": amount, "currency": currency, "merchant": merchant},
                raw=f"spent {amount} {currency} at {merchant}",
            )
        )
        del i
    return out


def _build_meals(user_id: str, anchor: datetime, rng: random.Random, *, count: int) -> list[ObservationRow]:
    out: list[ObservationRow] = []
    for i in range(count):
        day_offset = rng.randint(-29, 0)
        meal_type, items = rng.choice(_MEALS)
        item = rng.choice(items)
        local_hour = {"breakfast": 8, "lunch": 13, "dinner": 19, "snack": 16}[meal_type]
        jitter = rng.randint(-30, 30)
        calories = rng.randint(200, 800)
        event_time = anchor + timedelta(days=day_offset, hours=local_hour - 8, minutes=jitter)
        out.append(
            ObservationRow(
                user_id=user_id,
                type="meal",
                event_time=event_time,
                tags={"meal_type": meal_type},
                fields={"meal": item, "meal_type": meal_type, "calories": calories},
                raw=f"{meal_type}: {item}",
            )
        )
        del i
    return out


def _build_moods(user_id: str, anchor: datetime, rng: random.Random, *, count: int) -> list[ObservationRow]:
    out: list[ObservationRow] = []
    for i in range(count):
        day_offset = rng.randint(-29, 0)
        score = rng.randint(2, 5)
        note = rng.choice(_MOOD_NOTES)
        event_time = anchor + timedelta(days=day_offset, hours=14, minutes=rng.randint(0, 59))
        out.append(
            ObservationRow(
                user_id=user_id,
                type="mood",
                event_time=event_time,
                tags={},
                fields={"score": score, "note": note},
                raw=f"mood {score}/5: {note}",
            )
        )
        del i
    return out


def _build_sleeps(user_id: str, anchor: datetime, rng: random.Random, *, count: int) -> list[ObservationRow]:
    out: list[ObservationRow] = []
    for i in range(count):
        day_offset = rng.randint(-29, 0)
        hours = round(rng.uniform(5.0, 8.5), 1)
        event_time = anchor + timedelta(days=day_offset, hours=-1, minutes=rng.randint(0, 59))
        out.append(
            ObservationRow(
                user_id=user_id,
                type="sleep",
                event_time=event_time,
                tags={},
                fields={"hours": hours},
                raw=f"slept {hours}h",
            )
        )
        del i
    return out


def _build_habits(user_id: str, anchor: datetime, rng: random.Random, *, count: int) -> list[ObservationRow]:
    out: list[ObservationRow] = []
    for i in range(count):
        day_offset = rng.randint(-29, 0)
        habit, note = rng.choice(_HABITS)
        event_time = anchor + timedelta(days=day_offset, hours=7, minutes=rng.randint(0, 59))
        out.append(
            ObservationRow(
                user_id=user_id,
                type="habit",
                event_time=event_time,
                tags={"habit": habit},
                fields={"habit": habit, "note": note},
                raw=f"{habit}: {note}",
            )
        )
        del i
    return out
