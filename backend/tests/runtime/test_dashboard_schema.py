"""Round-trip ``DashboardPlan`` through Pydantic and assert the wire format
matches the TypeScript ``dashboard/web/lib/plan.ts`` contract.

The TS side is camelCase (``generatedAt``, ``lastTouch``, ``trackerName``,
``shapeRead``, ``greetingPrefix``, ``illustrationId``); the Python side is
snake_case for ergonomics. Both must work for input and ``model_dump
(mode='json', by_alias=True)`` must always emit camelCase for storage and
the renderer.
"""
from __future__ import annotations

import pytest

from backend.dashboard.schema import DashboardPlan


def _morning_plan_dict() -> dict:
    """Hand-built plan covering intro, rows, all alias-bearing fields, and
    one each of the bigger block kinds. Mirrors what the LLM would emit."""
    return {
        "id": "plan:test-user:morning",
        "generatedAt": "2026-04-26T07:30:00+05:30",
        "user": {"name": "Aarav", "initial": "A"},
        "thesis": "the morning is yours; pick one open loop and finish it before noon.",
        "moment": "morning",
        "blocks": [],
        "intro": {
            "kicker": "saturday morning",
            "greetingPrefix": "good morning,",
            "accent": "Aarav",
            "greetingSuffix": ".",
            "place": "mumbai · 29° · soft light",
            "illustrationId": "tea",
        },
        "rows": [
            {
                "title": "today",
                "meta": "two open loops, one tracker",
                "cols": [
                    {
                        "size": "two-thirds",
                        "block": {
                            "type": "todo-list",
                            "title": "before lunch",
                            "items": [
                                {
                                    "id": "todo-1",
                                    "label": "send the deck to luca",
                                    "meta": "owed 3 days",
                                    "source": "open_loop",
                                    "done": False,
                                    "action": {
                                        "v": "complete_pick",
                                        "pickId": "todo-1",
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "size": "third",
                        "block": {
                            "type": "tracker-grid",
                            "title": "today",
                            "items": [
                                {
                                    "id": "water",
                                    "title": "water",
                                    "value": "1.2",
                                    "unit": "L",
                                    "sub": "of 3L",
                                    "progress": 0.4,
                                    "icon": "drop",
                                    "tone": "moss",
                                    "tint": "moss",
                                    "action": {
                                        "v": "log_value",
                                        "tracker": "water",
                                        "value": 0.25,
                                        "unit": "L",
                                    },
                                }
                            ],
                        },
                    },
                ],
            },
            {
                "cols": [
                    {
                        "size": "full",
                        "block": {
                            "type": "calendar-shape",
                            "title": "today's shape",
                            "shapeRead": "two meetings clustered after lunch; mornings free.",
                            "slots": [
                                {
                                    "id": "slot-1",
                                    "at": "10:30",
                                    "label": "deep work",
                                    "duration": 90,
                                    "kind": "focus",
                                }
                            ],
                        },
                    }
                ],
            },
        ],
    }


@pytest.mark.unit
def test_round_trip_preserves_camelcase_aliases() -> None:
    """Input camelCase → parse → dump by_alias must equal input for every
    aliased field. Catches drift between TS contract and Pydantic schema."""
    src = _morning_plan_dict()

    plan = DashboardPlan.model_validate(src)
    dumped = plan.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert dumped["generatedAt"] == src["generatedAt"]
    assert dumped["intro"]["greetingPrefix"] == "good morning,"
    assert dumped["intro"]["greetingSuffix"] == "."
    assert dumped["intro"]["illustrationId"] == "tea"

    cal_block = dumped["rows"][1]["cols"][0]["block"]
    assert cal_block["shapeRead"] == "two meetings clustered after lunch; mornings free."

    todo_action = dumped["rows"][0]["cols"][0]["block"]["items"][0]["action"]
    assert todo_action["pickId"] == "todo-1"


@pytest.mark.unit
def test_snake_case_input_also_parses() -> None:
    """Python callers should be able to construct a plan with snake_case
    keys; the dump still produces camelCase for the wire."""
    plan = DashboardPlan.model_validate(
        {
            "id": "plan:x",
            "generated_at": "2026-04-26T07:30:00+05:30",
            "user": {"name": "Aarav", "initial": "A"},
            "thesis": "small reset.",
            "moment": "morning",
            "blocks": [],
            "rows": [
                {
                    "cols": [
                        {
                            "size": "full",
                            "block": {"type": "footer", "text": "see you at noon."},
                        }
                    ]
                }
            ],
            "intro": {
                "kicker": "saturday",
                "greeting_prefix": "good morning,",
                "accent": "Aarav",
                "illustration_id": "tea",
            },
        }
    )
    dumped = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "generatedAt" in dumped
    assert dumped["intro"]["greetingPrefix"] == "good morning,"
    assert dumped["intro"]["illustrationId"] == "tea"


@pytest.mark.unit
def test_unknown_block_keys_are_ignored_not_rejected() -> None:
    """Forward-compat: TS may add fields before the Pydantic mirror does.
    The schema must drop unknown keys instead of raising."""
    plan = DashboardPlan.model_validate(
        {
            "id": "plan:x",
            "generatedAt": "2026-04-26T00:00:00+00:00",
            "user": {"name": "X", "initial": "X"},
            "thesis": "noted.",
            "moment": "morning",
            "blocks": [
                {
                    "type": "thesis",
                    "sentence": "okay.",
                    "futureField": "ignored",
                }
            ],
        }
    )
    assert plan.thesis == "noted."
    assert plan.blocks[0].type == "thesis"


@pytest.mark.unit
def test_invalid_action_verb_rejected() -> None:
    """Discriminated union should raise on an unknown ``v`` value."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DashboardPlan.model_validate(
            {
                "id": "plan:x",
                "generatedAt": "2026-04-26T00:00:00+00:00",
                "user": {"name": "X", "initial": "X"},
                "thesis": "x",
                "moment": "morning",
                "blocks": [],
                "rows": [
                    {
                        "cols": [
                            {
                                "size": "full",
                                "block": {
                                    "type": "todo-list",
                                    "title": "t",
                                    "items": [
                                        {
                                            "id": "i1",
                                            "label": "l",
                                            "meta": "m",
                                            "source": "s",
                                            "action": {"v": "not_a_real_verb"},
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ],
            }
        )
