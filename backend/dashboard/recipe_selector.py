"""Pick which recipes to surface based on what the user DOESN'T have.

The recipe mosaic should stay useful past Day 1. The selector reads the
user's current state — live attentions + connected integrations — and
filters the bank to recipes whose ``provides`` capability tags don't
already exist on the user's surface.

Two consumption paths:

1. ``select_for_day_one(user_id, k=5)`` — full Pinterest-style mosaic
   (5 tall + short tiles). Used when the user has thin signal.

2. ``select_for_established(user_id, k=4)`` — compact chips variant
   (4 short tiles) shown on Page 2 mind rail as a "more I could run
   for you" footer. Skips recipes whose ``requires`` toolkits aren't
   connected (those go in c-permission instead).

Both return a list of ``Recipe`` rows in priority order: highest-impact
gaps first.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select

from backend.db.session import async_session
from backend.dashboard.recipe_bank import RECIPE_BANK, Recipe
from db.models import AttentionRow, Integration

logger = logging.getLogger(__name__)


# Mapping from recipe ``provides`` tags → predicates over the user's
# attention rows. When the predicate matches a row, the recipe is
# considered "already running" and gets skipped.
#
# Match shape: (card_type, subject_keyword) — checked case-insensitively
# against AttentionRow.card and AttentionRow.payload['spec']['subject'].
# Keep predicates loose so a tracker named "calorie count" still
# matches the "tracks_calories" tag.
_PROVIDES_MATCHERS: dict[str, tuple[str, str]] = {
    "tracks_calories":          ("tally", "calorie"),
    "tracks_hydration":         ("tally", "water"),
    "tracks_sleep":              ("tally", "sleep"),
    "tracks_spend":              ("tally", "spend"),
    "inbox_brief":               ("brief", "inbox"),
    "week_brief":                ("brief", "week"),
    "weekly_money_brief":       ("brief", "spend"),
    "subscription_watcher":     ("event_stream", "subscription"),
    "trips_watcher":             ("event_stream", "trip"),
    "market_watcher":            ("event_stream", "market"),
    "people_staleness_watcher": ("event_stream", "person"),
    "new_attendee_prep":        ("prep_doc", "meeting"),
    "weekly_loops_sweep":       ("brief", "loop"),
    "nightly_reflection":       ("ping", "reflect"),
    "weekly_avoidance":          ("ping", "avoid"),
}


async def _existing_capabilities(user_id: str) -> set[str]:
    """Return the set of capability tags the user already has running.

    Walks live + paused attentions; matches each against the predicate
    table. A user with no attentions returns an empty set, so every
    recipe is a candidate. A user with a calorie tally + nightly
    reflection returns ``{"tracks_calories", "nightly_reflection"}``
    and the selector skips both recipes.
    """
    try:
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(AttentionRow).where(
                        AttentionRow.user_id == user_id,
                        AttentionRow.status.in_(("live", "paused")),
                    )
                )
            ).scalars().all()
    except Exception:
        logger.exception("recipe_selector: attention read failed user=%s", user_id)
        return set()

    have: set[str] = set()
    for tag, (card_match, subject_match) in _PROVIDES_MATCHERS.items():
        for row in rows:
            if (row.card or "").lower() != card_match:
                continue
            spec = (row.payload or {}).get("spec") or {}
            subject_obj = spec.get("subject") or {}
            subject_name = ""
            if isinstance(subject_obj, dict):
                subject_name = (subject_obj.get("name") or "").lower()
            elif isinstance(subject_obj, str):
                subject_name = subject_obj.lower()
            title = (row.title or "").lower()
            if subject_match in subject_name or subject_match in title:
                have.add(tag)
                break
    return have


# The integrations table normalises Google's products as ``provider=google``
# + ``product=gmail|calendar|drive|...`` while recipe ``requires`` uses
# the Composio toolkit slug (``gmail``, ``googlecalendar``, ``googledrive``,
# ``googledocs``). Map (provider, product) → toolkit slug so the gating
# works regardless of which side stores the canonical slug.
_PROVIDER_PRODUCT_TO_TOOLKIT: dict[tuple[str, str], str] = {
    ("google", "gmail"): "gmail",
    ("google", "calendar"): "googlecalendar",
    ("google", "drive"): "googledrive",
    ("google", "docs"): "googledocs",
}


async def _connected_toolkits(user_id: str) -> set[str]:
    """Return the toolkit slugs the user has connected ('connected' status).

    Joins the integrations table to the recipe-side toolkit vocabulary.
    Adds (provider, product) explicitly AND each of (provider, product)
    individually, so a recipe whose ``requires`` is ``"gmail"`` matches
    a row stored as ``provider=google, product=gmail``, and a recipe
    whose ``requires`` is ``"googlecalendar"`` matches the same row's
    composed slug.
    """
    try:
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(Integration.provider, Integration.product, Integration.status)
                    .where(
                        Integration.user_id == user_id,
                        Integration.status == "connected",
                    )
                )
            ).all()
    except Exception:
        logger.exception("recipe_selector: integrations read failed user=%s", user_id)
        return set()

    toolkits: set[str] = set()
    for provider, product, _status in rows:
        prov = (provider or "").lower()
        prod = (product or "").lower()
        if prov:
            toolkits.add(prov)
        if prod:
            toolkits.add(prod)
        composed = _PROVIDER_PRODUCT_TO_TOOLKIT.get((prov, prod))
        if composed:
            toolkits.add(composed)
    return toolkits


def _missing_recipes(
    bank: Iterable[Recipe],
    have_caps: set[str],
    connected_toolkits: set[str],
    *,
    require_toolkits: bool,
) -> list[Recipe]:
    """Filter the bank to recipes that fill a gap.

    A recipe is a gap iff every tag in ``provides`` is missing from
    ``have_caps``. When ``require_toolkits`` is True, we also drop
    recipes whose ``requires`` aren't all connected — useful for the
    chips variant where we don't want to lure the user into tapping a
    recipe that immediately stalls on OAuth.
    """
    out: list[Recipe] = []
    for r in bank:
        if any(p in have_caps for p in r.provides):
            continue
        if require_toolkits and r.requires:
            if not all(tk in connected_toolkits for tk in r.requires):
                continue
        out.append(r)
    return out


def _prioritize(recipes: list[Recipe]) -> list[Recipe]:
    """Light prioritisation: spread across surfaces so the mosaic shows
    donna's range, not five trackers."""
    seen_surfaces: set[str] = set()
    primary: list[Recipe] = []
    secondary: list[Recipe] = []
    for r in recipes:
        if r.surface not in seen_surfaces:
            seen_surfaces.add(r.surface)
            primary.append(r)
        else:
            secondary.append(r)
    return primary + secondary


async def select_for_day_one(user_id: str, *, k: int = 5) -> list[Recipe]:
    """Full mosaic — 5 recipes spanning surfaces, gaps prioritised.

    Day 1 users typically have no attentions and no integrations, so
    the bank is barely filtered; surface-spread becomes the main
    signal. Established users still get a refresh — recipes they've
    already started drop out.
    """
    have = await _existing_capabilities(user_id)
    toolkits = await _connected_toolkits(user_id)
    candidates = _missing_recipes(
        RECIPE_BANK,
        have,
        toolkits,
        require_toolkits=False,  # Day 1 mosaic shows recipes that need OAuth too
    )
    return _prioritize(candidates)[:k]


async def select_for_established(user_id: str, *, k: int = 4) -> list[Recipe]:
    """Compact chips variant — 3-4 recipes filling specific gaps for users
    who already have signal but might want more.

    Skips recipes whose required integrations aren't connected (we don't
    want to lure into a stalled workflow). Skips recipes whose
    capability tag is already provided by an existing attention.
    """
    have = await _existing_capabilities(user_id)
    toolkits = await _connected_toolkits(user_id)
    candidates = _missing_recipes(
        RECIPE_BANK,
        have,
        toolkits,
        require_toolkits=True,
    )
    return _prioritize(candidates)[:k]


def recipe_to_item(r: Recipe) -> dict[str, str]:
    """Render a Recipe as the JSON shape the dashboard renderer expects.

    Mirrors the ``RecipeItem`` TS interface in ``dashboard/web/lib/plan.ts``.
    Tone / icon / size flow through; size defaults to "tall" for the
    mosaic variant (renderer ignores it on chips).
    """
    return {
        "title": r.title,
        "primer": r.primer,
        "tone": r.tone,
        "icon": r.icon,
        "body": r.body,
    }
