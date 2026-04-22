"""Renders the USER MODEL block for the system prompt.

Sync renderer takes a facts dict; async wrapper loads facts + living_profile.
"""
from __future__ import annotations

from backend.memory.user_facts.schema import Confidence, FactKey, Source

_ORDER = [
    FactKey.PREFERRED_NAME,
    FactKey.HOME_CITY,
    FactKey.CURRENT_CITY,
    FactKey.HOME_TIMEZONE,
    FactKey.CURRENT_TIMEZONE,
    FactKey.PROFESSION,
    FactKey.LIFE_STAGE,
    FactKey.AGE_GROUP,
    FactKey.HOUSEHOLD,
    FactKey.PRIMARY_LANGUAGE,
    FactKey.WAKE_TIME,
    FactKey.SLEEP_TIME,
]

_LABELS = {
    FactKey.PREFERRED_NAME: "name",
    FactKey.HOME_CITY: "home city",
    FactKey.CURRENT_CITY: "current city",
    FactKey.HOME_TIMEZONE: "home timezone",
    FactKey.CURRENT_TIMEZONE: "current timezone",
    FactKey.PROFESSION: "profession",
    FactKey.LIFE_STAGE: "life stage",
    FactKey.AGE_GROUP: "age group",
    FactKey.HOUSEHOLD: "household",
    FactKey.PRIMARY_LANGUAGE: "primary language",
    FactKey.WAKE_TIME: "wake time",
    FactKey.SLEEP_TIME: "sleep time",
}


def _is_informative(key: FactKey, fact: dict) -> bool:
    if (
        fact.get("source") == Source.DEFAULT.value
        and fact.get("confidence") == Confidence.MEDIUM.value
    ):
        return False
    return True


def render_user_model_block(facts: dict) -> str:
    if not facts:
        return ""
    present = [(k, facts[k.value]) for k in _ORDER if k.value in facts]
    has_signal = any(_is_informative(k, f) for k, f in present)
    if not has_signal:
        return ""
    lines = [f"  {_LABELS[k]}: {f.get('value', '')}" for k, f in present]
    return "USER MODEL\n" + "\n".join(lines)


async def load_and_render(user_id: str) -> str:
    """Load facts + living_profile from DB and render; empty string if nothing."""
    from backend.memory.user_facts.api import get_living_profile, get_user_facts

    facts = await get_user_facts(user_id)
    block = render_user_model_block(facts)
    profile = await get_living_profile(user_id)
    if profile:
        summary = profile.get("summary") or profile.get("narrative") or ""
        if summary:
            block = (block + "\n\nLIVING PROFILE\n" + str(summary)).strip()
    return block
