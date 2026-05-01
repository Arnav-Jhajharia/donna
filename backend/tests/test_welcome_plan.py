"""Tests for the Day-1 welcome dashboard fixture.

The welcome plan must be a fully valid ``DashboardPlan`` so the renderer
treats it identically to an LLM-composed plan. No special-case branches
on the frontend.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.dashboard.schema import (
    DashboardPlan,
    FooterBlock,
    HeroBlock,
    ThesisBlock,
)
from backend.dashboard.welcome import build_welcome_plan


def test_welcome_plan_validates_as_dashboard_plan():
    plan = build_welcome_plan(
        user_id="user-1",
        name="Aarav",
        timezone_name="Asia/Kolkata",
    )

    # Round-trip through the schema to confirm every field passes
    # discriminated-union validation. If a future schema tightening
    # breaks the fixture, this test fails before the fixture goes live.
    assert isinstance(plan, DashboardPlan)
    payload = plan.model_dump(mode="json", by_alias=True)
    DashboardPlan.model_validate(payload)


def test_welcome_plan_uses_users_name_and_initial():
    plan = build_welcome_plan(
        user_id="user-1",
        name="aarav",
        timezone_name="Asia/Kolkata",
    )
    assert plan.user.name == "aarav"
    assert plan.user.initial == "A"


def test_welcome_plan_falls_back_when_name_missing():
    plan = build_welcome_plan(
        user_id="user-1",
        name=None,
        timezone_name=None,
    )
    assert plan.user.name == "friend"
    assert plan.user.initial == "F"


def test_welcome_plan_has_three_blocks_in_voice():
    """One hero, one thesis, one footer. Day 1 is small on purpose."""
    plan = build_welcome_plan(
        user_id="user-1",
        name="ravi",
        timezone_name="Asia/Kolkata",
        now_local=datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert plan.moment == "morning"
    assert len(plan.blocks) == 3
    assert isinstance(plan.blocks[0], HeroBlock)
    assert isinstance(plan.blocks[1], ThesisBlock)
    assert isinstance(plan.blocks[2], FooterBlock)
    # voice rules: lowercase, no em dashes, no semicolons
    for block in plan.blocks:
        text = block.model_dump_json()
        assert "—" not in text
        assert ";" not in text


@pytest.mark.parametrize(
    "hour,expected_moment",
    [
        (3, "late"),
        (6, "dawn"),
        (9, "morning"),
        (12, "midday"),
        (16, "afternoon"),
        (19, "evening"),
        (22, "night"),
    ],
)
def test_welcome_plan_moment_tracks_local_hour(hour: int, expected_moment: str):
    plan = build_welcome_plan(
        user_id="user-1",
        name="ravi",
        timezone_name="Asia/Kolkata",
        now_local=datetime(
            2026, 5, 1, hour, 0, tzinfo=ZoneInfo("Asia/Kolkata")
        ),
    )
    assert plan.moment == expected_moment


def test_welcome_plan_id_is_stable_for_user():
    """Same user, same id. The welcome manifest is overwritten by the
    next ``update_dashboard``, but until then the id should be a stable
    handle for cache busting and event correlation."""
    a = build_welcome_plan(user_id="user-1", name="ravi", timezone_name=None)
    b = build_welcome_plan(user_id="user-1", name="ravi", timezone_name=None)
    assert a.id == b.id == "plan:user-1:welcome"


def test_welcome_plan_handles_invalid_timezone():
    plan = build_welcome_plan(
        user_id="user-1",
        name="ravi",
        timezone_name="Not/A/Real/TZ",
    )
    # Should still produce a valid moment and timestamp
    assert plan.moment in {
        "late", "dawn", "morning", "midday", "afternoon", "evening", "night"
    }
    assert plan.generated_at  # ISO string non-empty
