"""Decorate a user's current dashboard manifest with appropriate actions.

For blocks that map to a real attention (tally, open_loop, watch/event_stream,
brief, prep_doc), emits ``open_attention`` with the matched attention id so
tapping opens the AttentionSheet drawer.

For input affordances (quick_log, reflection), emits ``quick_log`` so the
chip writes a real observation.

For Donna proposals (offer/draft/decision/permission), emits the
appropriate accept/dismiss verbs against the matched attention id.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.models import AttentionRow, DashboardManifest
from db.session import async_session


def _ensure_id(it: dict[str, Any], prefix: str) -> str:
    if it.get("id"):
        return str(it["id"])
    new_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    it["id"] = new_id
    return new_id


async def _attentions_by_card(user_id: str) -> dict[str, list[dict[str, Any]]]:
    """Return live attentions grouped by card. Each entry is a flat dict
    with id + title + subject so we can pick the best match."""
    out: dict[str, list[dict[str, Any]]] = {}
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AttentionRow)
                .where(AttentionRow.user_id == user_id)
                .where(AttentionRow.status == "live")
            )
        ).scalars().all()
    for r in rows:
        payload = r.payload or {}
        spec = payload.get("spec") or {}
        subj = spec.get("subject") or {}
        out.setdefault(r.card or "?", []).append({
            "id": r.id,
            "title": (spec.get("title") or "").lower(),
            "subject": (subj.get("name") or "").lower() if isinstance(subj, dict) else "",
        })
    return out


def _pick_attention(
    pool: list[dict[str, Any]], hint: str
) -> str | None:
    """Pick the attention from ``pool`` whose title/subject best matches the hint."""
    if not pool:
        return None
    h = (hint or "").lower()
    if not h:
        return pool[0]["id"]
    # token overlap scoring
    h_tokens = {t for t in h.split() if len(t) >= 3}
    best, best_score = None, -1
    for a in pool:
        text = f"{a['title']} {a['subject']}"
        score = sum(1 for t in h_tokens if t in text)
        if score > best_score:
            best_score = score
            best = a
    return (best or pool[0])["id"]


def decorate_block(
    block: dict[str, Any],
    by_card: dict[str, list[dict[str, Any]]],
) -> None:
    btype = block.get("type")
    if btype == "c-tracker":
        items = block.get("items") or []
        first_title = (items[0].get("title") or "habit").lower() if items else "habit"
        att_id = _pick_attention(by_card.get("tally", []), first_title)
        if att_id:
            block["actions"] = [
                {"v": "quick_log", "kind": first_title, "payload": "+1"},
                {"v": "open_attention", "attentionId": att_id},
            ]
        else:
            block["actions"] = [
                {"v": "quick_log", "kind": first_title, "payload": "+1"},
            ]
    elif btype == "c-watch":
        att_id = _pick_attention(by_card.get("event_stream", []), "watch")
        if att_id:
            block["actions"] = [{"v": "open_attention", "attentionId": att_id}]
    elif btype == "c-brief":
        title = (block.get("title") or "").lower()
        att_id = _pick_attention(by_card.get("brief", []), title)
        if att_id:
            block["actions"] = [{"v": "open_attention", "attentionId": att_id}]
    elif btype == "c-prep":
        att_id = _pick_attention(by_card.get("prep_doc", []), "prep")
        if att_id:
            block["actions"] = [{"v": "open_attention", "attentionId": att_id}]
    elif btype == "c-openloop":
        for it in block.get("items") or []:
            _ensure_id(it, "loop")
        att_id = _pick_attention(by_card.get("open_loop", []), "")
        if att_id:
            block["actions"] = [{"v": "open_attention", "attentionId": att_id}]
    elif btype == "c-streak":
        att_id = _pick_attention(by_card.get("tally", []), (block.get("title") or "").lower())
        block["actions"] = [{"v": "quick_log", "kind": "streak", "payload": "logged"}]
        if att_id:
            block["actions"].append({"v": "open_attention", "attentionId": att_id})
    elif btype == "c-reminder":
        for it in block.get("items") or []:
            _ensure_id(it, "rem")
        block["actions"] = []
    elif btype == "c-quicklog":
        chips = block.get("chips") or []
        block["actions"] = [
            {"v": "quick_log", "kind": (c.get("label") or "note").lower(), "payload": c.get("label")}
            for c in chips[:4]
        ] or [{"v": "quick_log", "kind": "note", "payload": "..."}]
    elif btype == "c-pick":
        pick_id = _ensure_id(block, "pick")
        block["actions"] = [
            {"v": "complete_pick", "pickId": pick_id},
        ]
    elif btype == "c-offer":
        att_id = _pick_attention(by_card.get("ping", []) + by_card.get("tally", []), block.get("title", "")) or _ensure_id(block, "offer")
        block["actions"] = [
            {"v": "accept_attention", "attentionId": att_id},
            {"v": "dismiss_attention", "attentionId": att_id},
        ]
    elif btype == "c-draft":
        did = _ensure_id(block, "draft")
        block["actions"] = [{"v": "accept_draft", "draftId": did}]
    elif btype == "c-decision":
        dec_id = _ensure_id(block, "dec")
        opts = block.get("options") or []
        block["actions"] = [
            {"v": "decide_option", "decisionId": dec_id, "optionId": _ensure_id(o, "opt")}
            for o in opts[:3]
        ]
    elif btype == "c-confront":
        att_id = _pick_attention(by_card.get("brief", []) + by_card.get("ping", []), "") or _ensure_id(block, "conf")
        block["actions"] = [
            {"v": "accept_attention", "attentionId": att_id},
            {"v": "dismiss_attention", "attentionId": att_id},
        ]
    elif btype == "c-reflection":
        block["actions"] = [{"v": "quick_log", "kind": "reflection", "payload": "saved"}]
    elif btype == "c-permission":
        att_id = _pick_attention(by_card.get("ping", []), block.get("title", "")) or _ensure_id(block, "perm")
        block["actions"] = [{"v": "accept_attention", "attentionId": att_id}]
    elif btype == "c-person":
        block["actions"] = [{"v": "open_relationship", "personId": _ensure_id(block, "person")}]
    elif btype == "c-read":
        block["actions"] = [
            {"v": "open_news", "newsId": _ensure_id(block, "read")},
            {"v": "complete_pick", "pickId": _ensure_id(block, "read")},
        ]


def walk_blocks(node: Any, by_card: dict[str, list[dict[str, Any]]]) -> None:
    if isinstance(node, dict):
        if node.get("type"):
            decorate_block(node, by_card)
        for v in node.values():
            walk_blocks(v, by_card)
    elif isinstance(node, list):
        for v in node:
            walk_blocks(v, by_card)


async def main(user_id: str) -> int:
    by_card = await _attentions_by_card(user_id)
    print(
        f"live attentions for {user_id[:8]}: "
        + " · ".join(f"{c}={len(v)}" for c, v in sorted(by_card.items()))
    )
    async with async_session() as session:
        row = (
            await session.execute(
                select(DashboardManifest).where(
                    DashboardManifest.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            print(f"no manifest for {user_id[:8]}", file=sys.stderr)
            return 1
        plan = dict(row.plan_jsonb or {})
        walk_blocks(plan, by_card)
        row.plan_jsonb = plan
        flag_modified(row, "plan_jsonb")
        await session.commit()
    try:
        from backend.dashboard.manifest_events import broadcast_changed
        await broadcast_changed(user_id)
    except Exception:
        pass
    print(json.dumps(plan, indent=2)[:1200])
    print("…")
    print(f"decorated manifest for {user_id[:8]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.user_id)))
