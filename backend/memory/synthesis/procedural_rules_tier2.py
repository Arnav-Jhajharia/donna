"""Tier-2 procedural rule synthesis (ADR 0008 semantics, spec §8).

Replaces the user's Tier-2 rules wholesale on each run. Pulls recent
observations + open loops + graph hits to propose a compact ruleset, then
overwrites the Tier-2 slice of procedural_rules for the user.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "procedural_rules_tier2.md"
_TIER = "tier2"
_LOOKBACK_DAYS = 14
_MAX_RULES = 20


class _Rule(BaseModel):
    when: str = Field(description="Trigger condition — user state or intent.")
    then: str = Field(description="How Donna should behave.")
    rationale: str = Field(default="", description="Why this rule exists.")


class _RuleBatch(BaseModel):
    rules: list[_Rule] = Field(default_factory=list)


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text()
    except Exception:
        return (
            "Synthesize at most 20 concise behavioral rules from the observations "
            "and recent conversation. Return JSON: {rules: [{when, then, rationale}]}."
        )


async def _collect_evidence(user_id: str) -> str:
    """Pull recent observations + open loops; render as compact text."""
    from sqlalchemy import select

    from backend.db.models import Observation, OpenLoop
    from backend.db.session import async_session

    since = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    lines: list[str] = []
    async with async_session() as session:
        obs_rows = (
            await session.execute(
                select(Observation)
                .where(Observation.user_id == user_id, Observation.event_time >= since)
                .order_by(Observation.event_time.desc())
                .limit(120)
            )
        ).scalars().all()
        for o in obs_rows:
            lines.append(f"OBS[{o.type}] {o.fields}")

        loop_rows = (
            await session.execute(
                select(OpenLoop).where(OpenLoop.user_id == user_id).limit(30)
            )
        ).scalars().all()
        for l in loop_rows:
            lines.append(f"LOOP[{l.status}] {l.content}")
    return "\n".join(lines) or "(no recent observations)"


async def synthesize_tier2_rules(user_id: str) -> list[dict] | None:
    """Generate a fresh Tier-2 ruleset and replace the existing slice."""
    evidence = await _collect_evidence(user_id)
    prompt = _load_prompt().format(evidence=evidence)
    batch = await call_structured(
        model="claude-haiku-4-5-20251001",
        system_prompt=prompt,
        user_message="Synthesize.",
        schema=_RuleBatch,
        max_tokens=1200,
    )
    if batch is None:
        return None

    rules = [r.model_dump() for r in batch.rules[:_MAX_RULES]]

    from sqlalchemy import delete

    from backend.db.models import ProceduralRule
    from backend.db.session import async_session

    now = datetime.now(timezone.utc)
    async with async_session() as session:
        await session.execute(
            delete(ProceduralRule).where(
                ProceduralRule.user_id == user_id,
                ProceduralRule.type == _TIER,
            )
        )
        for r in rules:
            session.add(
                ProceduralRule(
                    user_id=user_id,
                    type=_TIER,
                    rule=f"WHEN {r['when']}\nTHEN {r['then']}",
                    quote=r.get("rationale") or None,
                    last_confirmed_at=now,
                )
            )
        await session.commit()

    logger.info(
        "procedural_rules_tier2: replaced slice for user=%s (%d rules)",
        user_id[:8], len(rules),
    )
    return rules
