from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.memory.synthesis.temporal_brief import (
    IMPLEMENTATIONS,
    BriefImplementation,
    TemporalEvidence,
    TemporalItem,
    build_all_temporal_briefs,
    build_stress_cases,
    build_temporal_brief,
    make_temporal_windows,
    stress_test_implementations,
    summarize_stress_results,
)
from backend.memory.synthesis.temporal_eval_dataset import (
    build_diverse_stress_cases,
    dataset_summary,
)


def test_temporal_windows_are_user_timezone_week_boundaries():
    now = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    windows = make_temporal_windows(now, "Asia/Singapore")

    assert windows.this_week_start.isoformat() == "2026-04-19T16:00:00+00:00"
    assert windows.next_week_start.isoformat() == "2026-04-26T16:00:00+00:00"


def test_all_five_temporal_implementations_render():
    evidence = TemporalEvidence(
        user_id="u1",
        now=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
        timezone="Asia/Singapore",
        chat_messages=[
            TemporalItem(
                kind="chat",
                text="this week i am shipping donna memory",
                at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
                role="user",
            )
        ],
        calendar=[
            TemporalItem(
                kind="calendar",
                text="investor call",
                at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
            )
        ],
    )

    briefs = asyncio.run(build_all_temporal_briefs(evidence, use_claude=False))

    assert set(briefs) == {impl.value for impl in IMPLEMENTATIONS}
    for name, brief in briefs.items():
        rendered = brief.render()
        assert name in rendered
        assert "SITUATION BRIEF" in rendered
        assert len(rendered) <= 3500


def test_claude_variant_falls_back_without_live_call():
    evidence = TemporalEvidence(
        user_id="u1",
        now=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
        timezone="Asia/Singapore",
        chat_messages=[
            TemporalItem(
                kind="chat",
                text="last week was apartment search",
                at=datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc),
                role="user",
            )
        ],
    )

    brief = asyncio.run(
        build_temporal_brief(
            evidence,
            BriefImplementation.CLAUDE_SYNTHESIS,
            use_claude=False,
        )
    )

    assert brief.implementation == "claude_synthesis"
    assert "fallback" in " ".join(brief.stale_or_uncertain).lower()
    assert "apartment" in brief.render().lower()


def test_stress_test_scores_all_implementations():
    results = stress_test_implementations(build_stress_cases())
    summary = summarize_stress_results(results)

    assert len(results) == len(build_stress_cases()) * len(IMPLEMENTATIONS)
    assert {row["implementation"] for row in summary} == {impl.value for impl in IMPLEMENTATIONS}
    assert summary[0]["average_score"] >= summary[-1]["average_score"]


def test_diverse_temporal_dataset_has_breadth():
    cases = build_diverse_stress_cases()
    summary = dataset_summary(cases)

    assert summary["cases"] >= 20
    assert summary["timezone_count"] >= 8
    assert summary["with_observations"] == summary["cases"]
    assert summary["with_open_loops"] == summary["cases"]
    assert summary["with_calendar"] == summary["cases"]
    assert summary["overload_cases"] >= 6


def test_diverse_temporal_dataset_scores_windowed_timeline_well():
    cases = build_diverse_stress_cases()
    results = stress_test_implementations(cases)
    summary = summarize_stress_results(results)
    by_impl = {row["implementation"]: row for row in summary}

    assert by_impl["windowed_timeline"]["average_score"] >= 80
    assert by_impl["recent_context"]["average_score"] < by_impl["windowed_timeline"]["average_score"]
