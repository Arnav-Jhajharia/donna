"""Push-up tracker — reactive (subscriber) feature.

Different shape than Hydration (counter+scheduled cron) and Gratitude
(scheduled prompt). This one is **reactive**: when a *workout*
observation lands, Donna asks "how many push-ups?" 60s later. The
answer comes back as a *pushup* observation that updates state.

Mechanism:
- ``observations`` declares both:
    - ``pushup`` (owner=primary)   — the feature's own counter type
    - ``workout`` (owner=subscriber) — listens but doesn't claim
- ``post_observation`` hook ``prompt_pushup_after_workout`` fires for
  workout writes, creates a one-shot DonnaSchedule whose handler is the
  registered cron handler ``render_pushup_prompt``.
- ``post_observation`` hook ``update_pushup_state`` fires for pushup
  writes, increments today/week/total/pr counters.
- ``cron`` declares a Sunday 18:00 weekly recap.

Edge cases handled:
- multiple workouts logged in quick succession → only one prompt
  pending at a time (dedup against existing pending DonnaSchedule rows)
- user already logged push-ups today → skip the prompt (no point asking
  if they already told us)
- workout logged late at night (after quiet hours) → still asks; the
  user can ignore. Quiet-hour gating is Phase 4b territory.
"""
from __future__ import annotations

from backend.features.library import _pushup_handlers  # noqa: F401


FEATURE_MANIFEST = {
    "template_id": "pushup_tracker",
    "name": "Push-ups",
    "description": (
        "tracks push-ups; asks 'how many?' a minute after each workout "
        "log; weekly recap on sunday evening"
    ),
    "surface": "body",
    "icon": "flame",
    "tone": "rust",
    "manifest_version": "1.0",

    "config_schema": {
        "prompt_delay_sec": {
            "type": "int",
            "default": 60,
            "min": 0,
            "max": 600,
            "description": (
                "Seconds to wait after a workout observation before "
                "asking. 0 = immediate; longer gives the user time to "
                "log set details first."
            ),
        },
        "weekly_review_dow": {
            "type": "int",
            "default": 0,           # Sunday
            "min": 0,
            "max": 6,
        },
        "weekly_review_time": {
            "type": "str",
            "default": "18:00",
        },
    },

    "integrations": [],

    "observations": [
        {
            "type": "pushup",
            "owner": "primary",
            "fields_required": {
                "reps": {"type": "int", "min": 0, "max": 1000},
            },
            "fields_optional": {
                "set_index": {"type": "int", "min": 1, "max": 30},
                "note": {"type": "str", "max_len": 200},
            },
            "aggregation": {
                "today_count":  "sum(reps) where today",
                "week_count":   "sum(reps) where last_7d",
                "total_count":  "sum(reps)",
                "pr":           "max(reps)",
            },
            "extractor_hint": (
                "user reporting push-ups, pushups, push ups. extract "
                "the count as 'reps'. multiple sets get separate "
                "observations with set_index."
            ),
        },
        {
            # Subscriber: listen but don't claim. workout observations
            # are owned by another feature (or untyped); we just react.
            "type": "workout",
            "owner": "subscriber",
            "fields_required": {},
            "fields_optional": {},
            "aggregation": {},
            "extractor_hint": "",
        },
    ],

    "attentions": [],

    "cron": [
        {
            "name": "weekly_recap",
            "schedule": "0 18 * * 0",   # Sunday 18:00
            "tz_aware": True,
            "handler": "render_pushup_weekly_recap",
            "recurrence": "weekly",
        },
    ],

    "dashboard_cards": [
        {
            "archetype":   "c-tracker",
            "variant":     "borderless",
            "domain":      "body",
            "render_when": "state.today_count > 0",
            "priority":    19,
            "fill": {
                "label":   "push-ups",
                "unit":    "reps",
                "value":   "{state.today_count}",
                "tone":    "rust",
                "history": "observations.type='pushup' last 7d, daily sum",
            },
        },
        {
            "archetype":   "c-streak",
            "variant":     "badge",
            "domain":      "body",
            "render_when": "state.pr > 0",
            "priority":    14,
            "fill": {
                "label":   "PR",
                "value":   "{state.pr}",
                "tone":    "rust",
            },
        },
    ],

    "tools_required": ["log_observation"],
    "tools_exposed": [],

    "hooks": [
        {"event": "post_observation", "handler": "prompt_pushup_after_workout"},
        {"event": "post_observation", "handler": "update_pushup_state"},
    ],

    "onboarding": {
        "ask": (
            "want me to track push-ups? i'll ask 'how many?' a minute "
            "after each workout log. weekly recap on sunday."
        ),
        "default_active_for": ["fitness-conscious"],
        "install_kind": "user_confirms",
    },

    "recipe": {
        "id": "pushup_after_workout",
        "title": "track my push-ups",
        "primer": (
            "track my push-ups from now on. ask 'how many?' a minute "
            "after each workout. weekly recap on sunday."
        ),
        "provides": ("tracks_pushups",),
        "requires": (),
        "body": (
            "every time you log a workout, donna asks 'how many push-ups?' "
            "after a brief pause. she remembers your PR. sunday recap "
            "shows the week's volume."
        ),
    },
}
