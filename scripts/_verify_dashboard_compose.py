"""One-shot: run compose_manifest for a user and print the resulting plan.

Exists only to verify the LIVE-attention routing landed. After it works
we can delete this file or fold it into a /observe panel.
"""
from __future__ import annotations

import asyncio
import json
import sys

from donna_runtime.env import load_dotenv

load_dotenv()


async def _run(user_id: str) -> None:
    from backend.dashboard.compose import (
        _format_brief,
        _read_live_attentions,
        _read_offered_attentions,
        _read_inputs,
        _resolve_now_local,
        compose_manifest,
    )

    inputs = await _read_inputs(user_id)
    if inputs is None:
        print(f"user {user_id} not found")
        sys.exit(1)
    user, observations, open_loops = inputs
    offered = _read_offered_attentions(user_id)
    live = _read_live_attentions(user_id)
    now_local = _resolve_now_local(user.timezone)

    print("=" * 72)
    print(f"BRIEF for {user.name} ({user.id})")
    print("=" * 72)
    print(_format_brief(
        user=user,
        now_local=now_local,
        observations=observations,
        open_loops=open_loops,
        offered_attentions=offered,
        live_attentions=live,
        trigger="verify_compose",
    ))
    print("=" * 72)
    print(f"  observations: {len(observations)}")
    print(f"  open_loops:   {len(open_loops)}")
    print(f"  OFFERED:      {len(offered)}")
    print(f"  LIVE:         {len(live)}")
    print()

    print("compose_manifest running...")
    plan = await compose_manifest(user_id=user_id, trigger="verify_compose")
    if plan is None:
        print("compose returned None (LLM error or DB issue)")
        sys.exit(2)

    payload = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    rows = payload.get("rows") or []

    print("=" * 72)
    print(f"PLAN: thesis={payload.get('thesis')!r}")
    print(f"      moment={payload.get('moment')}  rows={len(rows)}")
    print("=" * 72)

    block_types: dict[str, int] = {}
    rendered_attention_ids: list[str] = []
    rendered_subjects: list[str] = []

    for ri, row in enumerate(rows, 1):
        title = row.get("title")
        cells = row.get("cols") or []
        size_summary = " / ".join(str(c.get("size")) for c in cells)
        print(f"\nrow {ri} ({size_summary}){' — ' + title if title else ''}")
        for c in cells:
            block = c.get("block") or {}
            t = block.get("type")
            block_types[t] = block_types.get(t, 0) + 1
            print(f"  [{c.get('size'):>14}] {t:<18}", end="")
            if t == "tracker-grid":
                items = block.get("items") or []
                print(f"  ({len(items)} items)")
                for it in items:
                    print(
                        f"      · {it.get('title')}: "
                        f"{it.get('value')}{('/' + str(it.get('target'))) if it.get('target') else ''} "
                        f"{it.get('unit') or ''}"
                    )
                    rendered_subjects.append(str(it.get("title", "")).lower())
            elif t == "tracker-starter":
                action = block.get("action") or {}
                attn_id = action.get("attentionId") or action.get("attention_id")
                if attn_id:
                    rendered_attention_ids.append(attn_id)
                print(
                    f"  trackerName={block.get('trackerName')!r}  "
                    f"action.v={action.get('v')!r}"
                )
            elif t == "reminders":
                items = block.get("items") or []
                print(f"  ({len(items)} items)")
                for it in items:
                    print(f"      · {it.get('label')!r} at={it.get('at')!r}")
            elif t == "nudge-grid":
                items = block.get("items") or []
                print(f"  ({len(items)} items)")
                for it in items:
                    print(f"      · {it.get('title')!r} ({it.get('variant')})")
            elif t in ("whisper", "thesis", "witness", "footer"):
                body = block.get("body") or block.get("sentence") or block.get("text") or ""
                print(f"  {body[:80]!r}")
            elif t == "open-loops":
                items = block.get("items") or []
                print(f"  ({len(items)} items)")
                for it in items:
                    print(f"      · {it.get('title')!r}")
            elif t == "todo-list":
                items = block.get("items") or []
                print(f"  ({len(items)} items)")
            else:
                print()

    print()
    print("=" * 72)
    print("BLOCK TYPE COUNTS:", block_types)
    print(f"OFFERED attention ids referenced: {rendered_attention_ids}")
    print(f"LIVE subjects rendered: {rendered_subjects}")
    print("=" * 72)

    # Persist so the actual dashboard reflects what we just printed.
    from backend.dashboard.store import upsert_manifest

    await upsert_manifest(user_id, plan, trigger="verify_compose")
    print("manifest persisted — refresh the dashboard to see it")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m scripts._verify_dashboard_compose <user_id>")
        sys.exit(1)
    asyncio.run(_run(sys.argv[1]))
