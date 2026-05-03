"""Backfill the identity card (User.facts) from Graphiti.

Donna's USER MODEL block is the always-loaded identity layer the brain
sees on every turn. Graphiti has been ingesting episodes for weeks and
already knows things like "the user is a student at NUS" — but those
facts never got promoted into User.facts (the slot the renderer reads).

This script bridges that gap one-time: query Graphiti for identity-
shaped facts, ask Haiku to map them into the FactKey schema, write via
the existing ``update_user_fact`` API.

Usage:
    python -m scripts.backfill_identity_from_graphiti +919875486045 +919836046413

Or by user_id directly:
    python -m scripts.backfill_identity_from_graphiti --user-id 986cbc94-...

Idempotent: ``update_user_fact`` only writes when the resolved fact
differs from existing. Re-running won't downgrade higher-confidence or
USER_CORRECTION-sourced facts.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.db.session import async_session
from backend.memory.clients.graphiti import search_facts
from backend.memory.retrieval.structured import call_structured
from backend.memory.user_facts.api import update_user_fact
from backend.memory.user_facts.schema import Confidence, FactKey, Source
from db.models import User

logger = logging.getLogger(__name__)


_IDENTITY_QUERIES = (
    "school university student",
    "lives in city home",
    "work job role profession employer",
    "expertise skills good at",
    "key relationships family friends",
    "current goals plans working towards",
    "values beliefs cares about",
    "hobbies interests free time",
    "background origin where from",
)


_SYSTEM_PROMPT = """You map raw graph facts about a person into a structured identity card.

You'll be given:
  - the person's known name (may be empty)
  - a bag of relational facts pulled from a knowledge graph

Map them to fields. Rules:
  - Use ONLY signal that's repeated, recent, or stated as identity (not
    one-off behaviours like "had pasta yesterday").
  - Short values. School should be the institution name (e.g., "NUS").
    Expertise / hobbies / goals are short comma-separated phrases.
  - If a field has no clean signal, leave it null. Half-signal is worse
    than nothing — it pollutes the prompt.
  - Names of family/close friends only when the graph explicitly marks
    them as relationships (sister, brother, partner, etc.). Don't invent
    relationship roles.
  - Values are stable beliefs ("shipping fast", "calm-first communication"),
    not transient moods.
  - Goals are what the person is actively working towards over weeks/months
    ("ship donna v2", "finish degree"), not today's todos.

Reject the speculative. If you're not sure, return null."""


class IdentityCard(BaseModel):
    """Result of mapping graph facts into the FactKey schema."""

    education_institution: Optional[str] = Field(
        default=None,
        description="University/school name only, e.g. 'NUS'.",
    )
    employer: Optional[str] = Field(
        default=None,
        description="Current employer name. Skip if person is a student or self-employed founder.",
    )
    profession: Optional[str] = Field(
        default=None,
        description="Role/title — 'building Donna', 'student', 'software engineer'. Avoid opinion-shaped values.",
    )
    expertise: Optional[str] = Field(
        default=None,
        description="Comma-separated skills/areas, max 5 items. e.g. 'ml engineering, product design'.",
    )
    current_city: Optional[str] = Field(
        default=None,
        description="Where they currently live, city only.",
    )
    home_city: Optional[str] = Field(
        default=None,
        description="Where they're from / hometown, city only. May be same as current.",
    )
    key_relationships: Optional[str] = Field(
        default=None,
        description="Comma-separated 'name: role' pairs, e.g. 'maya: sister, aniroodh: cofounder'. Only relationships explicitly named in the graph.",
    )
    current_goals: Optional[str] = Field(
        default=None,
        description="Comma-separated active goals, max 3 items. e.g. 'ship donna v2, finish nus degree'.",
    )
    values: Optional[str] = Field(
        default=None,
        description="Comma-separated stable beliefs, max 3 items. Skip if not clearly stated.",
    )
    hobbies: Optional[str] = Field(
        default=None,
        description="Comma-separated, max 3 items.",
    )
    life_stage: Optional[str] = Field(
        default=None,
        description="Short phrase: 'university student', 'early career', 'founder', etc. Skip if unclear.",
    )


_FIELD_TO_KEY = {
    "education_institution": FactKey.EDUCATION_INSTITUTION,
    "employer": FactKey.EMPLOYER,
    "profession": FactKey.PROFESSION,
    "expertise": FactKey.EXPERTISE,
    "current_city": FactKey.CURRENT_CITY,
    "home_city": FactKey.HOME_CITY,
    "key_relationships": FactKey.KEY_RELATIONSHIPS,
    "current_goals": FactKey.CURRENT_GOALS,
    "values": FactKey.VALUES,
    "hobbies": FactKey.HOBBIES,
    "life_stage": FactKey.LIFE_STAGE,
}


def _admin_url() -> tuple[str | None, str | None, str | None]:
    """Read backend URL + admin creds from env. Used when the local
    Graphiti driver can't reach Railway-internal DNS."""
    base = os.getenv("DONNA_BACKEND_URL", "").rstrip("/") or None
    user = os.getenv("ADMIN_USER", "admin")
    pw = os.getenv("ADMIN_PASSWORD") or None
    return base, user, pw


def _fetch_graphiti_via_admin(
    base: str, user: str, pw: str, user_id: str, query: str, limit: int = 10
) -> list[dict]:
    """HTTP fallback when direct Graphiti driver isn't reachable.

    The admin route runs inside the donna pod which can resolve the
    Railway-internal FalkorDB host. Same data, just one network hop.
    """
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    qs = urllib.parse.urlencode({"query": query, "limit": str(limit)})
    url = f"{base}/api/admin/{user_id}/memory/graphiti?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read())
    return body.get("facts") or []


async def gather_graphiti_facts(user_id: str) -> list[str]:
    """Pull identity-shaped facts from Graphiti across multiple queries.

    Strategy:
      - When DONNA_BACKEND_URL points at a non-localhost host (typical
        for a developer running this from a laptop via ``railway run``),
        use the admin HTTP route. The Railway-internal FalkorDB host
        isn't resolvable from outside the Railway network, but the donna
        service can reach it.
      - Otherwise (in-process / running inside the pod), use the
        Graphiti driver directly. Same data; one fewer hop.
    """
    base, admin_user, admin_pw = _admin_url()
    prefer_http = bool(
        base
        and admin_pw
        and not (base.startswith("http://localhost") or base.startswith("http://127."))
    )
    if prefer_http:
        logger.info("using admin HTTP route at %s", base)

    seen: set[str] = set()
    facts: list[str] = []
    for q in _IDENTITY_QUERIES:
        rows: list = []
        if prefer_http:
            try:
                rows = _fetch_graphiti_via_admin(
                    base, admin_user, admin_pw, user_id, q, limit=10
                )
            except Exception as exc:
                logger.warning("admin graphiti http %r failed: %s", q, exc)
                continue
        else:
            try:
                rows = await search_facts(user_id=user_id, query=q, limit=10)
            except Exception as exc:
                logger.warning("graphiti driver %r failed: %s", q, exc)
                continue

        for r in rows or []:
            text = (
                (r.get("fact") if isinstance(r, dict) else None)
                or (r.get("content") if isinstance(r, dict) else None)
                or (r.get("text") if isinstance(r, dict) else None)
                or str(r)
            )
            text = (text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            facts.append(text)
    return facts


async def resolve_user(arg: str) -> User | None:
    async with async_session() as s:
        # Try as user_id first (UUID-shape).
        if "-" in arg or len(arg) == 36:
            row = (
                await s.execute(select(User).where(User.id == arg))
            ).scalar_one_or_none()
            if row is not None:
                return row
        # Phone — strip leading + and lookup. Phones are stored without +
        # in the user table (e.g. '919875486045').
        phone = arg.lstrip("+").strip()
        row = (
            await s.execute(select(User).where(User.phone == phone))
        ).scalar_one_or_none()
        return row


async def backfill_one(user: User, dry_run: bool = False) -> dict:
    user_id = user.id
    name = user.name or ""
    print(f"\n=== {name or '<no name>'} · {user.phone} · {user_id[:8]} ===")

    facts = await gather_graphiti_facts(user_id)
    if not facts:
        print("  no graphiti facts — skipping")
        return {"user_id": user_id, "skipped": "no_graphiti_facts"}

    print(f"  graphiti facts gathered: {len(facts)}")
    for f in facts[:8]:
        print(f"    · {f[:160]}")
    if len(facts) > 8:
        print(f"    ... +{len(facts) - 8} more")

    user_message = (
        f"Person's known name: {name or '(unknown)'}\n\n"
        "Graph facts:\n" + "\n".join(f"- {f}" for f in facts[:60])
    )
    card = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=_SYSTEM_PROMPT,
        user_message=user_message,
        schema=IdentityCard,
        max_tokens=600,
        timeout=20.0,
    )
    if card is None:
        print("  haiku mapping failed — skipping")
        return {"user_id": user_id, "skipped": "haiku_failed"}

    print(f"\n  proposed identity card:")
    payload = card.model_dump()
    proposed_writes: list[tuple[FactKey, str]] = []
    for field, value in payload.items():
        if value is None or not str(value).strip():
            continue
        key = _FIELD_TO_KEY.get(field)
        if key is None:
            continue
        proposed_writes.append((key, str(value).strip()))
        print(f"    {key.value} = {value!r}")

    if dry_run:
        print("  dry-run: skipping writes")
        return {
            "user_id": user_id,
            "dry_run": True,
            "proposed": [(k.value, v) for k, v in proposed_writes],
        }

    print()
    written: list[str] = []
    for key, value in proposed_writes:
        try:
            await update_user_fact(
                user_id=user_id,
                key=key.value,
                value=value,
                source=Source.CONVERSATION_EXTRACTED,
                confidence=Confidence.HIGH,
            )
            written.append(key.value)
            print(f"    wrote {key.value} = {value!r}")
        except Exception as exc:
            print(f"    FAILED {key.value}: {exc}")
    return {"user_id": user_id, "written": written}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "targets",
        nargs="*",
        help="Phones (with or without +) or user_ids to backfill.",
    )
    p.add_argument("--user-id", action="append", default=[])
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    targets = list(args.targets) + list(args.user_id)
    if not targets:
        print("no targets supplied — pass phones or --user-id", file=sys.stderr)
        return 2

    summary: list[dict] = []
    for t in targets:
        user = await resolve_user(t)
        if user is None:
            print(f"\n=== {t} ===\n  user not found — skipping")
            summary.append({"target": t, "error": "not_found"})
            continue
        summary.append(await backfill_one(user, dry_run=args.dry_run))

    print("\n=== SUMMARY ===")
    for s in summary:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
