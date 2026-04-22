"""Nightly living profile synthesis (spec §8).

Pulls graph facts across multiple search angles, runs a Haiku call to shape
them into a structured situational profile, and writes the result to
`users.living_profile` (JSONB). Per plan: scheduler wiring is deferred.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from backend.memory.clients.graphiti import search_facts
from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "living_profile.md"

_SEARCH_QUERIES = (
    "current situation challenges problems stress",
    "people relationships team colleagues",
    "goals progress milestones deadlines",
    "recent changes decisions updates",
)


class _KeyPerson(BaseModel):
    name: str
    role: str = ""
    current_dynamic: str = ""


class _Profile(BaseModel):
    current_situation: str = ""
    active_tensions: list[str] = Field(default_factory=list)
    key_people: list[_KeyPerson] = Field(default_factory=list)
    what_changed_this_week: list[str] = Field(default_factory=list)
    watch_for_tomorrow: list[str] = Field(default_factory=list)
    emotional_temperature: str = "focused"


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text()
    except Exception:
        return "Synthesize a nightly profile from these facts. Return structured JSON."


async def _collect_facts(user_id: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for q in _SEARCH_QUERIES:
        for f in await search_facts(user_id, q, limit=8):
            fact = f.get("fact") or ""
            if fact and fact not in seen:
                seen.add(fact)
                out.append(f)
    return out


async def synthesize_nightly_profile(user_id: str) -> dict | None:
    """Build and persist the nightly living profile. Returns the profile dict."""
    facts = await _collect_facts(user_id)
    if len(facts) < 2:
        logger.info(
            "living_profile: user=%s — too few facts (%d), skipping",
            user_id[:8], len(facts),
        )
        return None

    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        name = user.name if user and user.name else "the user"

    facts_text = "\n".join(
        f"- [{(f.get('valid_at') or 'recent')[:10]}] {f['fact']}"
        for f in facts
        if f.get("fact")
    )

    prompt = _load_prompt().format(name=name, facts=facts_text)
    profile = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=prompt,
        user_message="Synthesize.",
        schema=_Profile,
        max_tokens=1000,
    )
    if profile is None:
        return None

    out = profile.model_dump()
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["facts_used"] = len(facts)

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user:
            user.living_profile = out
            await session.commit()
            logger.info(
                "living_profile: stored for user=%s (%d facts, temp=%s)",
                user_id[:8], len(facts), out.get("emotional_temperature", "?"),
            )
    return out
