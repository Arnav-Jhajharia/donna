"""Features Phase 1 e2e test against Arnav (prod Supabase).

Run with: python scripts/test_features_phase1_arnav.py <step>

Steps:
  schema   — verify migration 0024 landed cleanly
  install  — install hydration_tracker for Arnav with target_glasses=10
  inspect  — read back the feature row + attentions + schedule rows
  log      — log a hydration observation, verify feature_id auto-tagged
  reinstall — call install_feature again, expect created=False
  all      — run every step end-to-end
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import text

from db.session import async_session

ARNAV = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"


async def step_schema():
    async with async_session() as c:
        ver = (await c.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        print(f"alembic_version = {ver!r}")
        feat_cnt = (await c.execute(text("SELECT count(*) FROM features"))).scalar()
        print(f"features rows   = {feat_cnt}")
        for tbl in ("attentions", "observations", "donna_schedule", "procedural_rules"):
            r = await c.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    f"WHERE table_name = :t AND column_name = 'feature_id'"
                ),
                {"t": tbl},
            )
            row = r.fetchone()
            print(f"{tbl}.feature_id     = {row}")
        idx = await c.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = ANY(:t) AND indexname LIKE '%feature%' "
                "ORDER BY indexname"
            ),
            {"t": ["features", "attentions", "observations", "donna_schedule"]},
        )
        print("feature indexes =", [r[0] for r in idx.fetchall()])


async def step_install():
    from backend.features.install import install_feature

    res = await install_feature(
        user_id=ARNAV,
        template_id="hydration_tracker",
        config_overrides={"target_glasses": 10},
    )
    print("install result:")
    print(f"  feature_id    = {res.feature_id}")
    print(f"  created       = {res.created}")
    print(f"  attention_ids = {res.attention_ids}")
    print(f"  schedule_ids  = {res.schedule_ids}")


async def step_inspect():
    async with async_session() as c:
        r = await c.execute(
            text(
                "SELECT id, template_id, name, surface, status, config, state, manifest_version "
                "FROM features WHERE user_id = :u ORDER BY created_at"
            ),
            {"u": ARNAV},
        )
        rows = r.fetchall()
        print(f"features for arnav: {len(rows)}")
        for row in rows:
            print(f"  id={row[0]} template={row[1]} name={row[2]} surface={row[3]} status={row[4]}")
            print(f"    config={row[5]}")
            print(f"    state={row[6]} manifest_version={row[7]}")

        if not rows:
            print("(no features installed yet)")
            return

        feature_id = rows[0][0]

        r = await c.execute(
            text(
                "SELECT id, status, payload FROM attentions "
                "WHERE feature_id = :f ORDER BY created_at"
            ),
            {"f": feature_id},
        )
        att_rows = r.fetchall()
        print(f"attentions tagged with feature_id={feature_id}: {len(att_rows)}")
        for ar in att_rows:
            print(f"  attention id={ar[0]} status={ar[1]}")
            print(f"    payload={ar[2]}")

        r = await c.execute(
            text(
                "SELECT id, origin, recurrence, fire_at, status, recurrence_meta FROM donna_schedule "
                "WHERE feature_id = :f ORDER BY fire_at"
            ),
            {"f": feature_id},
        )
        sch_rows = r.fetchall()
        print(f"schedules tagged with feature_id={feature_id}: {len(sch_rows)}")
        for sr in sch_rows:
            print(f"  schedule id={sr[0]} origin={sr[1]} recurrence={sr[2]} fire_at={sr[3]} status={sr[4]}")
            print(f"    recurrence_meta={sr[5]}")


async def step_log():
    from backend.memory.tools.log_observation import log_observation

    res = await log_observation(
        user_id=ARNAV,
        type="hydration",
        fields={"glasses": 1},
        raw="logging 1 glass for phase 1 test",
    )
    print("log_observation result:")
    print(f"  {res}")

    async with async_session() as c:
        r = await c.execute(
            text(
                "SELECT id, type, fields, feature_id, created_at FROM observations "
                "WHERE user_id = :u AND type = 'hydration' "
                "ORDER BY created_at DESC LIMIT 5"
            ),
            {"u": ARNAV},
        )
        for row in r.fetchall():
            print(f"  obs id={row[0]} type={row[1]} feature_id={row[3]} fields={row[2]} created_at={row[4]}")


async def step_lifecycle():
    """Exercise the Phase 2 lifecycle tools against the live Arnav feature."""
    from backend.features.lifecycle import (
        archive_feature,
        list_features,
        pause_feature,
        resume_feature,
        update_feature_config,
    )

    print("listing features (status=active):")
    for f in await list_features(user_id=ARNAV, status="active"):
        print(f"  - {f.template_id} ({f.status}) config={f.config}")

    print("\nupdate_feature_config target_glasses=12:")
    f = await update_feature_config(
        user_id=ARNAV,
        template_id="hydration_tracker",
        config_patch={"target_glasses": 12},
    )
    print(f"  result config={f.config if f else None}")

    print("\npause_feature:")
    f = await pause_feature(user_id=ARNAV, template_id="hydration_tracker")
    print(f"  status={f.status if f else None} paused_until={f.paused_until if f else None}")

    print("\nlist_features (no filter, all statuses):")
    for f in await list_features(user_id=ARNAV):
        print(f"  - {f.template_id} ({f.status})")

    print("\nresume_feature:")
    f = await resume_feature(user_id=ARNAV, template_id="hydration_tracker")
    print(f"  status={f.status if f else None}")

    print("\n(skipping archive — leaving feature live for now)")


async def step_reinstall():
    from backend.features.install import install_feature

    res = await install_feature(
        user_id=ARNAV,
        template_id="hydration_tracker",
        config_overrides={"target_glasses": 12},
    )
    print("re-install result:")
    print(f"  feature_id    = {res.feature_id}")
    print(f"  created       = {res.created} (expect False)")
    print(f"  attention_ids = {res.attention_ids} (expect empty)")
    print(f"  schedule_ids  = {res.schedule_ids} (expect empty)")


STEPS = {
    "schema": step_schema,
    "install": step_install,
    "inspect": step_inspect,
    "log": step_log,
    "reinstall": step_reinstall,
    "lifecycle": step_lifecycle,
}


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1]
    if name == "all":
        for s in ("schema", "install", "inspect", "log", "inspect", "reinstall", "inspect"):
            print(f"\n=== {s} ===")
            await STEPS[s]()
        return
    if name not in STEPS:
        print(f"unknown step: {name}")
        print(__doc__)
        sys.exit(2)
    await STEPS[name]()


if __name__ == "__main__":
    asyncio.run(main())
