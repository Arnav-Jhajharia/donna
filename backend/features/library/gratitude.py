"""Gratitude practice — Tier B reference manifest.

Proves a different feature shape than Hydration: cron-driven reflection
instead of counter-driven tracking. The point is that the same manifest
schema accommodates both, with no archetype-specific code in install /
lifecycle / dashboard wiring.

Shape:
- one observation type (`gratitude`) with a free-text ``note`` field
- ZERO scheduled attentions (no nudges between prompts)
- one daily cron at 21:30 user-local that asks the prompt
- one weekly review cron Sunday 18:00 that summarises the week
- one dashboard card (c-reflection variant) when there are entries
- recipe entry so the bank can offer the practice to users without it

The handlers register at module import via ``_gratitude_handlers`` so
the registry's library walk wires them up automatically.
"""
from __future__ import annotations

from backend.features.library import _gratitude_handlers  # noqa: F401


FEATURE_MANIFEST = {
    # Identity
    "template_id": "gratitude_practice",
    "name": "Gratitude",
    "description": (
        "nightly reflection practice; one short prompt at 21:30, "
        "weekly recap on Sunday evening"
    ),
    "surface": "mind",
    "icon": "heart",
    "tone": "amber",
    "manifest_version": "1.0",

    # Per-user settings
    "config_schema": {
        "prompt_time": {
            "type": "str",
            "default": "21:30",
            "description": "User-local HH:MM the nightly prompt fires.",
        },
        "weekly_review_dow": {
            "type": "int",
            "default": 0,           # Sunday in cron's 0-6 (Sun=0..Sat=6)
            "min": 0,
            "max": 6,
        },
        "weekly_review_time": {
            "type": "str",
            "default": "18:00",
        },
    },

    # No external integrations.
    "integrations": [],

    # Owned observation type.
    "observations": [
        {
            "type": "gratitude",
            "owner": "primary",
            "fields_required": {
                "note": {"type": "str", "max_len": 1000},
            },
            "fields_optional": {
                "tags": {"type": "list"},
            },
            "aggregation": {
                "today_count":  "count(*) where today",
                "week_count":   "count(*) where last_7d",
            },
            "extractor_hint": (
                "user expressing thanks, appreciation, gratitude, "
                "noting something good. capture the note verbatim if "
                "short, summarise if long."
            ),
        },
    ],

    # No attentions — gratitude is cron-only. Different from hydration,
    # which has both tally + ping. Proves features can declare empty
    # ``attentions`` and the install flow handles it.
    "attentions": [],

    # Two crons: nightly prompt + weekly recap.
    "cron": [
        {
            "name": "nightly_prompt",
            # 30 21 * * * — 21:30 daily.
            "schedule": "30 21 * * *",
            "tz_aware": True,
            "handler": "render_gratitude_prompt",
            "recurrence": "daily",
        },
        {
            "name": "weekly_recap",
            # 0 18 * * 0 — Sunday 18:00.
            "schedule": "0 18 * * 0",
            "tz_aware": True,
            "handler": "render_gratitude_weekly_recap",
            "recurrence": "weekly",
        },
    ],

    # Dashboard card — a c-reflection on the mind rail, only when
    # entries exist this week.
    "dashboard_cards": [
        {
            "archetype":   "c-reflection",
            "variant":     "italic",
            "domain":      "mind",
            "render_when": "state.week_count > 0",
            "priority":    18,
            "fill": {
                "label":      "gratitude this week",
                "value":      "{state.week_count}",
                "tone":       "amber",
                "history":    "observations.type='gratitude' last 7d",
            },
        },
    ],

    # Tools.
    "tools_required": ["log_observation"],
    "tools_exposed": [],

    # Hooks — the post_observation handler updates state counters.
    "hooks": [
        {"event": "post_observation", "handler": "update_gratitude_state"},
    ],

    # Onboarding.
    "onboarding": {
        "ask": (
            "want to start a nightly gratitude practice? one short prompt "
            "at 21:30, weekly recap on sunday."
        ),
        "default_active_for": ["reflective"],
        "install_kind": "user_confirms",
    },

    # Recipe — surfaces in the bank for users who don't have it yet.
    "recipe": {
        "id": "nightly_gratitude_practice",
        "title": "nightly gratitude",
        "primer": (
            "start a nightly gratitude practice. one short prompt at "
            "21:30, weekly recap on sunday evening."
        ),
        "provides": ("gratitude_practice",),
        "requires": (),
        "body": (
            "donna asks one short prompt at 21:30 each night. you answer "
            "in a sentence. on sundays at 18:00, she sends back the week."
        ),
    },
}
