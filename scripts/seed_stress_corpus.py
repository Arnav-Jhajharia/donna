"""Seed the memory stress-test corpus for synthetic user "Kai".

Idempotent: deletes Kai's rows (by fixed user_id) before inserting.
Leaves other users untouched — never truncates tables.

Usage:
    python scripts/seed_stress_corpus.py                 # default anchor = utcnow
    python scripts/seed_stress_corpus.py --anchor 2026-04-25T00:00:00
    python scripts/seed_stress_corpus.py --brief fresh   # pick a situation brief variant
    python scripts/seed_stress_corpus.py --dry-run       # build rows, skip DB writes

Graphiti and Supermemory writes are stubbed by default (plan calls for
"fake shim for offline runs"). Enable with DONNA_SEED_GRAPHITI=1 and/or
DONNA_SEED_SUPERMEMORY=1 once those clients are reachable.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._seed_corpus.anchor import AnchorWindow, resolve_anchor
from scripts._seed_corpus.briefs import BriefVariant, build_brief_variants
from scripts._seed_corpus.calendar import build_calendar_rows
from scripts._seed_corpus.chat import build_chat_rows
from scripts._seed_corpus.observations import build_observation_rows
from scripts._seed_corpus.open_loops import build_open_loop_rows
from scripts._seed_corpus.profile import SEED_USER_ID, build_profile_row

logger = logging.getLogger("seed_stress_corpus")

_DEFAULT_SEED = 42


@dataclass(frozen=True)
class SeedPlan:
    """Materialized row counts for verification / dry-run reporting."""

    anchor: AnchorWindow
    brief: BriefVariant
    chat_count: int
    observation_count: int
    open_loop_count: int
    calendar_count: int


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=str, default=None, help="ISO-8601 anchor datetime (UTC)")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument(
        "--brief",
        choices=["fresh", "3d_stale", "14d_stale"],
        default="fresh",
        help="Which situation brief freshness variant to store.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate rows without writing.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    plan = asyncio.run(_run(args))
    print(
        "seed corpus "
        f"anchor={plan.anchor.anchor.isoformat()} "
        f"brief={plan.brief.name} "
        f"chat={plan.chat_count} obs={plan.observation_count} "
        f"loops={plan.open_loop_count} cal={plan.calendar_count} "
        f"dry_run={args.dry_run}"
    )


async def _run(args: argparse.Namespace) -> SeedPlan:
    anchor = resolve_anchor(args.anchor)
    rng = random.Random(args.seed)
    brief = _select_brief(args.brief, anchor.anchor)

    profile = build_profile_row(anchor.anchor)
    chat_rows = build_chat_rows(profile.id, anchor.anchor, rng)
    observation_rows = build_observation_rows(profile.id, anchor.anchor, rng)
    open_loop_rows = build_open_loop_rows(profile.id, anchor.anchor)
    calendar_rows = build_calendar_rows(profile.id, anchor.anchor)

    plan = SeedPlan(
        anchor=anchor,
        brief=brief,
        chat_count=len(chat_rows),
        observation_count=len(observation_rows),
        open_loop_count=len(open_loop_rows),
        calendar_count=len(calendar_rows),
    )

    if args.dry_run:
        return plan

    await _write_all(
        profile=profile,
        brief=brief,
        chat_rows=chat_rows,
        observation_rows=observation_rows,
        open_loop_rows=open_loop_rows,
        calendar_rows=calendar_rows,
    )
    return plan


def _select_brief(name: str, anchor: datetime) -> BriefVariant:
    variants = {v.name: v for v in build_brief_variants(anchor)}
    if name not in variants:
        raise SystemExit(f"unknown brief variant: {name}")
    return variants[name]


# -- Writers -----------------------------------------------------------------


async def _write_all(
    *,
    profile: Any,
    brief: BriefVariant,
    chat_rows: list[Any],
    observation_rows: list[Any],
    open_loop_rows: list[Any],
    calendar_rows: list[Any],
) -> None:
    from sqlalchemy import delete

    from db.models import (
        CalendarEntry,
        ChatMessage,
        DonnaInstance,
        Observation,
        OpenLoop,
        User,
    )
    from db.session import async_session

    async with async_session() as session:
        await session.execute(delete(Observation).where(Observation.user_id == profile.id))
        await session.execute(delete(DonnaInstance).where(DonnaInstance.user_id == profile.id))
        await session.execute(delete(OpenLoop).where(OpenLoop.user_id == profile.id))
        await session.execute(delete(CalendarEntry).where(CalendarEntry.user_id == profile.id))
        await session.execute(delete(ChatMessage).where(ChatMessage.user_id == profile.id))
        await session.execute(delete(User).where(User.id == profile.id))
        await session.flush()

        user_row = User(
            id=profile.id,
            phone=profile.phone,
            name=profile.name,
            profession=profile.profession,
            timezone=profile.timezone,
            wake_time=profile.wake_time,
            sleep_time=profile.sleep_time,
            onboarding_complete=profile.onboarding_complete,
            onboarding_goals=profile.onboarding_goals,
            facts=profile.facts,
            living_profile={"situation_brief": brief.payload},
            is_sandbox=profile.is_sandbox,
            created_at=profile.created_at,
            last_active_at=profile.last_active_at,
        )
        session.add(user_row)

        instance_by_type: dict[str, DonnaInstance] = {}
        for obs in observation_rows:
            instance = instance_by_type.get(obs.type)
            if instance is None:
                instance = DonnaInstance(
                    user_id=profile.id,
                    primitive="track",
                    connector="whatsapp_manual",
                    label=obs.type,
                    config={"type": obs.type},
                    status="active",
                )
                session.add(instance)
                await session.flush()
                instance_by_type[obs.type] = instance
            session.add(
                Observation(
                    user_id=profile.id,
                    instance_id=instance.id,
                    type=obs.type,
                    event_time=obs.event_time,
                    tags=obs.tags,
                    fields=obs.fields,
                    raw=obs.raw,
                )
            )

        for row in chat_rows:
            session.add(
                ChatMessage(
                    user_id=profile.id,
                    role=row.role,
                    content=row.content,
                    is_proactive=row.is_proactive,
                    created_at=row.created_at,
                )
            )

        for row in open_loop_rows:
            session.add(
                OpenLoop(
                    user_id=profile.id,
                    content=row.content,
                    source_message=row.source_message,
                    created_at=row.created_at,
                    status=row.status,
                    resolved_at=row.resolved_at,
                )
            )

        for row in calendar_rows:
            session.add(
                CalendarEntry(
                    user_id=profile.id,
                    title=row.title,
                    start_time=row.start_time,
                    end_time=row.end_time,
                    location=row.location,
                    category=row.category,
                )
            )

        await session.commit()

    _maybe_seed_graphiti(profile.id)
    _maybe_seed_supermemory(profile.id)


def _maybe_seed_graphiti(user_id: str) -> None:
    if os.environ.get("DONNA_SEED_GRAPHITI") != "1":
        logger.info("graphiti seeding skipped (DONNA_SEED_GRAPHITI=1 to enable)")
        return
    logger.warning("graphiti seeding requested but not implemented yet; user_id=%s", user_id)


def _maybe_seed_supermemory(user_id: str) -> None:
    if os.environ.get("DONNA_SEED_SUPERMEMORY") != "1":
        logger.info("supermemory seeding skipped (DONNA_SEED_SUPERMEMORY=1 to enable)")
        return
    logger.warning("supermemory seeding requested but not implemented yet; user_id=%s", user_id)


# Re-export for test convenience.
__all__ = [
    "SeedPlan",
    "SEED_USER_ID",
    "main",
    "_run",
]


if __name__ == "__main__":
    main()
