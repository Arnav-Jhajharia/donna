"""Hydration tracker — Tier A reference manifest.

Smallest possible feature shape: one observation type, two attentions
(tally + cadenced ping), one dashboard card, one evening summary cron,
one recipe entry. Validates the install flow, FK tagging, and the
observation -> state update path.

The hook handlers (``update_hydration_state``,
``maybe_close_loop_on_glass_logged``, ``render_evening_summary``) are
declared but not implemented as live code in Phase 1 — Phase 1 only
needs the manifest to round-trip through registry + install. Stubs that
log are wired in Phase 4 when the hook dispatcher lands.
"""
from __future__ import annotations


FEATURE_MANIFEST = {
    # Identity
    "template_id": "hydration_tracker",
    "name": "Hydration",
    "description": (
        "tracks glasses of water; nudges every 2 hours during waking hours"
    ),
    "surface": "body",
    "icon": "drop",
    "tone": "moss",
    "manifest_version": "1.0",
    # Per-user settings
    "config_schema": {
        "target_glasses": {"type": "int", "default": 8, "min": 1, "max": 30},
        "remind_every_min": {
            "type": "int",
            "default": 120,
            "min": 30,
            "max": 480,
        },
        "quiet_start": {"type": "str", "default": "22:00"},
        "quiet_end": {"type": "str", "default": "07:00"},
    },
    # No integrations needed for the simplest tracker shape.
    "integrations": [],
    # Observation types this feature owns.
    "observations": [
        {
            "type": "hydration",
            "owner": "primary",
            "fields_required": {
                "glasses": {"type": "int", "min": 0, "max": 30}
            },
            "fields_optional": {
                "container_oz": {"type": "int"},
                "note": {"type": "str", "max_len": 200},
            },
            "aggregation": {
                "today": "sum(glasses)",
                "streak": (
                    "consecutive_days_where(today_sum >= "
                    "config.target_glasses)"
                ),
            },
            "extractor_hint": (
                "user mentioning water, glass, bottle, hydrate. count units."
            ),
        }
    ],
    # Attentions spawned on install.
    "attentions": [
        {
            "card": "tally",
            "subject_type": "habit",
            "cadence": "on_event",
            "title": "hydration tally",
            "description": "running glass count for today",
            "extractor_hint": "count glasses of water mentioned",
        },
        {
            "card": "ping",
            "subject_type": "habit",
            "cadence_template": "every_N_minutes",
            "cadence_param_key": "remind_every_min",
            "title": "hydration ping",
            "description": "cadenced nudge to drink water",
        },
    ],
    # Dashboard cards.
    "dashboard_cards": [
        {
            "archetype": "c-tracker",
            "variant": "borderless",
            "domain": "body",
            "render_when": "state.today_count > 0 OR is_evening",
            "priority": 20,
            "fill": {
                "label": "water",
                "unit": "glasses",
                "value": "{state.today_count}",
                "target": "{config.target_glasses}",
                "tone": "moss",
                "history": (
                    "observations.type='hydration' last 7d, daily count"
                ),
            },
        }
    ],
    # Tool wiring.
    "tools_required": ["log_observation"],
    "tools_exposed": [],
    # Hooks — declared but not wired live in Phase 1.
    "hooks": [
        {"event": "post_observation", "handler": "update_hydration_state"},
        {
            "event": "post_turn",
            "handler": "maybe_close_loop_on_glass_logged",
        },
    ],
    # Cron — evening summary.
    "cron": [
        {
            "name": "evening_summary",
            "schedule": "0 21 * * *",
            "tz_aware": True,
            "handler": "render_evening_summary",
            "recurrence": "daily",
        }
    ],
    "onboarding": {
        "ask": (
            "want me to track your water intake? i'll nudge every 2h."
        ),
        "default_active_for": ["health-conscious"],
        "install_kind": "user_confirms",
    },
    "recipe": {
        "id": "track_hydration",
        "title": "track my water",
        "primer": "track my water from now on",
        "provides": ("tracks_hydration",),
        "requires": (),
    },
}
