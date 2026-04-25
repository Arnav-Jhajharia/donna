"""User facts API — the single entry point for reads and writes.

Precedence rules in resolve_write (spec §12 pitfall):
  - No existing → write
  - USER_CORRECTION → always wins
  - Higher confidence wins
  - Ties broken by source rank
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.memory.user_facts.observation_writer import write_fact_observation
from backend.memory.user_facts.schema import (
    Confidence,
    Source,
    UserFact,
    confidence_rank,
    is_valid_fact_key,
    source_rank,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_write(
    existing: Optional[UserFact],
    new_value: str,
    new_source: Source,
    new_confidence: Confidence,
) -> UserFact:
    new_fact: UserFact = {
        "value": new_value,
        "source": new_source.value,
        "confidence": new_confidence.value,
        "updated_at": _now_iso(),
    }
    if existing is None:
        return new_fact
    if new_source == Source.USER_CORRECTION:
        return new_fact
    new_c = confidence_rank(new_confidence.value)
    old_c = confidence_rank(existing.get("confidence", Confidence.LOW.value))
    if new_c > old_c:
        return new_fact
    if new_c < old_c:
        return existing
    new_s = source_rank(new_source.value)
    old_s = source_rank(existing.get("source", Source.DEFAULT.value))
    if new_s > old_s:
        return new_fact
    return existing


async def update_user_fact(
    user_id: str,
    key: str,
    value: str,
    source: Source,
    confidence: Confidence,
) -> UserFact:
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from backend.db.models import User
    from backend.db.session import async_session

    if not is_valid_fact_key(key):
        raise ValueError(f"unknown fact key: {key}")

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError(f"user not found: {user_id}")

        facts = dict(user.facts or {})
        existing = facts.get(key)
        resolved = resolve_write(existing, value, source, confidence)

        if existing != resolved:
            facts[key] = resolved
            user.facts = facts
            flag_modified(user, "facts")
            await session.commit()
            logger.info(
                "user_facts: %s[%s]='%s' source=%s conf=%s",
                user_id[:8], key, value[:40], source.value, confidence.value,
            )
            await write_fact_observation(
                user_id=user_id, key=key, value=value, source=source, confidence=confidence
            )
            if key in ("current_timezone", "home_timezone"):
                try:
                    from backend.memory.tools.set_timezone import record_timezone_fact

                    await record_timezone_fact(
                        user_id,
                        value,
                        predicate=key,
                        source=source.value,
                    )
                except Exception:
                    logger.exception(
                        "user_facts: bitemporal mirror failed for %s", key
                    )
        return resolved


async def get_user_facts(user_id: str) -> dict[str, UserFact]:
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return {}
        return dict(user.facts or {})


async def get_living_profile(user_id: str) -> dict | None:
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        return dict(user.living_profile) if user.living_profile else None
