"""Render tests for the v2 Living Profile block (narrative-first contract).

The renderer now leads with the synthesizer's `narrative` field — a single
alive paragraph — and only adds compact one-liners for `key_people` and
`rhythm`. The bullet sections (misses, anomalies, watching, tensions,
changed_this_week) intentionally do NOT render: they bloat the prompt and
fight the "ambient knowing" voice. Those fields stay on the profile dict
for downstream code (pattern miners, proactive triggers).

Backward compat: profiles missing `narrative` fall back to
`current_situation` so old persisted blobs still render something useful
until the next nightly synth runs.
"""
from __future__ import annotations

from backend.memory.user_facts.rendering import (
    _v2_present,
    render_living_profile_block,
)


def _full_v2_profile() -> dict:
    return {
        "narrative": (
            "kai is mid-fundraise sprint, sleeping less than usual and "
            "leaning hard on cofounder calls. priya wired the first "
            "$500k clean this week. saurabh's term sheet is open since "
            "the 19th. maya shipped infra two days early — that's the "
            "one quiet win this week. the noise is hiring plan and the "
            "churn investigation ravi flagged. tone is focused, slightly "
            "stretched."
        ),
        "current_situation": (
            "mid-fundraise sprint, sleeping less than usual, "
            "leaning hard on cofounder calls"
        ),
        "active_tensions": [
            "investor pace vs founder energy",
            "alex blocked on auth",
        ],
        "key_people": [
            {
                "name": "sarah",
                "role": "cofounder",
                "current_dynamic": "syncing 2x daily, holding the line",
            },
            {
                "name": "alex",
                "role": "designer",
                "current_dynamic": "blocked on the auth handoff",
            },
        ],
        "what_changed_this_week": [
            "first principal call landed",
            "moved demo deck to figma",
        ],
        "watch_for_tomorrow": [
            "principal follow-up email",
            "design review at 14:00",
        ],
        "emotional_temperature": "focused",
        "rhythm": {
            "typical_wake_window": "06:30-07:45",
            "typical_first_engage_window": "07:30-08:30",
            "typical_message_gap_median_hours": 2.4,
            "typical_quiet_hours": "23:00-06:00",
        },
        "yesterday": {
            "one_line": "deep work morning, 3 calls afternoon, ate late",
            "misses": ["did not draft principal follow-up"],
            "anomalies": ["skipped lunch"],
        },
        "today_shape": (
            "design review at 14:00 is the anchor. principal email "
            "follow-up needs to land before noon. expect alex to ping "
            "about auth."
        ),
        "generated_at": "2026-04-26T02:00:00+00:00",
    }


def test_v2_present_detects_v2_profile():
    assert _v2_present(_full_v2_profile()) is True


def test_v2_present_rejects_legacy_profile():
    legacy = {"summary": "old narrative", "biography": {"overview": "x"}}
    assert _v2_present(legacy) is False


def test_v2_render_leads_with_narrative_paragraph():
    block = render_living_profile_block(_full_v2_profile())
    assert block.startswith("LIVING PROFILE")
    # Narrative starts on the line right after the header.
    second_line = block.split("\n", 2)[1]
    assert "mid-fundraise sprint" in second_line
    assert "saurabh" in second_line


def test_v2_render_includes_rhythm_with_engage_window():
    block = render_living_profile_block(_full_v2_profile())
    assert "rhythm:" in block
    assert "first engages 07:30-08:30" in block


def test_v2_render_lists_people_with_role_and_dynamic():
    block = render_living_profile_block(_full_v2_profile())
    assert "people:" in block
    assert "sarah" in block
    assert "cofounder" in block


def test_v2_render_drops_bullet_sections():
    """Misses, anomalies, watching, tensions, changed-this-week stay on
    the profile dict (downstream code uses them) but MUST NOT render
    into the LIVING PROFILE block — that's exactly the bullet salad
    that made the context feel like a database."""
    block = render_living_profile_block(_full_v2_profile())
    for forbidden in ("misses:", "anomalies:", "watching:", "tensions:", "changed this week:"):
        assert forbidden not in block, f"{forbidden} should not render"


def test_v2_render_caps_narrative_when_long():
    profile = _full_v2_profile()
    profile["narrative"] = "x" * 5000
    block = render_living_profile_block(profile)
    narrative_line = block.split("\n", 2)[1]
    # Narrative cap is 850 chars + ellipsis tail.
    assert len(narrative_line) <= 860, f"narrative not capped ({len(narrative_line)} chars)"


def test_v2_render_total_block_under_budget():
    block = render_living_profile_block(_full_v2_profile())
    # Narrative paragraph (~850 cap) + people line + rhythm line.
    # Should comfortably stay under the planned ~1.5KB ceiling.
    assert len(block) < 1700, f"v2 block too long ({len(block)} chars)"


def test_v2_render_falls_back_to_current_situation_when_narrative_missing():
    """Profiles persisted before the schema change have current_situation
    but no narrative. The renderer must fall back so we never render an
    empty LIVING PROFILE block in production."""
    profile = {
        "current_situation": "mid-fundraise sprint, running on fumes",
        "today_shape": "design review at 14:00, principal follow-up before noon",
    }
    block = render_living_profile_block(profile)
    assert "LIVING PROFILE" in block
    assert "mid-fundraise sprint" in block


def test_v2_render_skips_empty_supporting_lines():
    minimal = {"narrative": "running on fumes, prepping the demo"}
    block = render_living_profile_block(minimal)
    assert "running on fumes" in block
    # No people, no rhythm — those one-liners are conditional.
    assert "people:" not in block
    assert "rhythm:" not in block


def test_v2_render_returns_empty_for_empty_profile():
    assert render_living_profile_block({}) == ""
    assert render_living_profile_block(None) == ""


def test_legacy_profile_still_renders_via_fallback():
    legacy = {
        "summary": "the user is mid-fundraise",
        "biography": {
            "overview": "founder, building an ai product",
            "work": {"role": "ceo", "employer": "donna inc"},
            "interests": ["climbing", "synthesizers"],
        },
    }
    block = render_living_profile_block(legacy)
    assert "LIVING PROFILE" in block
    assert "BIOGRAPHY" in block
    assert "the user is mid-fundraise" in block
