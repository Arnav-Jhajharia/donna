"""One-shot cleanup: collapse duplicate active DonnaInstance rows.

The dedup logic in ``backend/dashboard/actions._maybe_materialize_instance``
prevents NEW duplicates, but rows created before that landed (or with
slightly different label phrasing — ``expense`` / ``expenses`` /
``daily expenses``) stay. This script normalises labels via
``donna.attention.noise.normalize_tracker_label`` and merges siblings
onto the oldest canonical row per user.

Idempotent: re-running is a no-op once status is ``merged``.

Usage:
    python -m scripts.dedup_donna_instances              # dry-run, all users
    python -m scripts.dedup_donna_instances --apply      # actually update
    python -m scripts.dedup_donna_instances --user <id>  # one user
    python -m scripts.dedup_donna_instances --apply --user <id>

Reads + writes:
- ``donna_instances`` — canonical row stays ``active``; siblings flip
  to ``status='merged'`` and gain ``config.merged_into_id`` for audit.
- ``observations`` — ``instance_id`` repointed to the canonical row so
  the tracker grids on the dashboard pick up the full history.
- ``donna_schedule`` — left alone; schedule rows reference attentions,
  not instances.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select, update

from db.models import DonnaInstance, Observation
from db.session import async_session
from donna.attention.noise import normalize_tracker_label

logger = logging.getLogger(__name__)


async def _list_active_track_instances(user_id: str | None) -> list[DonnaInstance]:
    async with async_session() as session:
        stmt = (
            select(DonnaInstance)
            .where(DonnaInstance.primitive == "track")
            .where(DonnaInstance.status == "active")
            .order_by(DonnaInstance.created_at.asc())
        )
        if user_id:
            stmt = stmt.where(DonnaInstance.user_id == user_id)
        rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


def _group_by_normalized_label(
    rows: list[DonnaInstance],
) -> dict[tuple[str, str], list[DonnaInstance]]:
    """Group instances by ``(user_id, normalize_tracker_label(label))``."""
    groups: dict[tuple[str, str], list[DonnaInstance]] = defaultdict(list)
    for r in rows:
        key = (r.user_id, normalize_tracker_label(r.label))
        groups[key].append(r)
    return groups


async def _merge_group(
    canonical: DonnaInstance,
    duplicates: list[DonnaInstance],
    *,
    apply: bool,
) -> int:
    """Repoint observations from ``duplicates`` onto ``canonical`` and
    flip the duplicates to ``status='merged'``. Returns the count of
    observation rows touched.

    ``apply=False`` leaves the DB untouched and only logs what would
    happen.
    """
    if not duplicates:
        return 0

    dup_ids = [d.id for d in duplicates]
    obs_count = 0

    async with async_session() as session:
        obs_count = (
            (
                await session.execute(
                    select(Observation).where(Observation.instance_id.in_(dup_ids))
                )
            )
            .scalars()
            .all()
        )
        obs_count = len(obs_count)

        if not apply:
            return obs_count

        await session.execute(
            update(Observation)
            .where(Observation.instance_id.in_(dup_ids))
            .values(instance_id=canonical.id)
        )

        for dup in duplicates:
            new_config = dict(dup.config or {})
            new_config["merged_into_id"] = canonical.id
            new_config.setdefault("original_label", dup.label)
            await session.execute(
                update(DonnaInstance)
                .where(DonnaInstance.id == dup.id)
                .values(status="merged", config=new_config)
            )
        await session.commit()

    return obs_count


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually mutate the DB (default is dry-run)",
    )
    parser.add_argument("--user", help="restrict to a single user_id")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )

    rows = await _list_active_track_instances(args.user)
    if not rows:
        print("no active track instances found")
        return

    groups = _group_by_normalized_label(rows)
    total_merged = 0
    total_obs_repointed = 0

    for (user_id, normalized), group in groups.items():
        if len(group) <= 1:
            continue
        canonical = group[0]
        duplicates = group[1:]
        labels = [d.label for d in duplicates]
        print(
            f"user={user_id[:8]} normalized={normalized!r}: "
            f"keeping {canonical.label!r} ({canonical.id[:8]}), "
            f"merging {len(duplicates)} sibling(s) {labels}"
        )
        obs_count = await _merge_group(canonical, duplicates, apply=args.apply)
        total_merged += len(duplicates)
        total_obs_repointed += obs_count

    verb = "merged" if args.apply else "would merge"
    print(
        f"\nsummary: {verb} {total_merged} duplicate instance(s); "
        f"{total_obs_repointed} observation row(s) repointed"
    )
    if not args.apply and total_merged:
        print("dry-run only — re-run with --apply to mutate.")


if __name__ == "__main__":
    asyncio.run(main())
