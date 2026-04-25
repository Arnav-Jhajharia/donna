"""The stress-test matrix itself.

Every row is one query + what we expect the BRAIN loop to do with it.
``expected_backends`` is which storage lanes *should* fire for a correct
answer; ``pass_criteria`` is the rubric the judge uses. ``section`` maps
back to the plan's 3.1–3.7 buckets so analysis can slice by category.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Section = Literal[
    "single_hop",
    "multi_hop",
    "temporal",
    "derivation",
    "correction",
    "failure_injection",
    "voice_coherence",
]


@dataclass(frozen=True)
class StressCase:
    id: str
    section: Section
    query: str
    expected_backends: tuple[str, ...]
    pass_criteria: str
    notes: str = ""
    # Pre-turn setup (only for correction / failure_injection rows).
    pre_turn_messages: tuple[str, ...] = field(default_factory=tuple)
    # Failure to inject before firing (only for failure_injection rows).
    inject_failure: str | None = None


def all_cases() -> list[StressCase]:
    """Return the full matrix. Order: 3.1 → 3.7."""
    return [
        *_single_hop(),
        *_multi_hop(),
        *_temporal(),
        *_derivation(),
        *_correction(),
        *_failure_injection(),
        *_voice_coherence(),
    ]


def _single_hop() -> list[StressCase]:
    return [
        StressCase(
            id="single_who_am_i",
            section="single_hop",
            query="who am i",
            expected_backends=("users.facts",),
            pass_criteria="reply mentions 'kai', 'founder', and 'singapore'",
            notes="rendered in USER MODEL; no tool call expected",
        ),
        StressCase(
            id="single_spend_this_week",
            section="single_hop",
            query="how much did i spend this week",
            expected_backends=("observations",),
            pass_criteria="reply cites a numeric total with currency",
        ),
        StressCase(
            id="single_what_is_tomorrow",
            section="single_hop",
            query="what's on tomorrow",
            expected_backends=("calendar",),
            pass_criteria="reply lists at least one upcoming event with a time",
        ),
        StressCase(
            id="single_what_am_i_forgetting",
            section="single_hop",
            query="what am i forgetting",
            expected_backends=("open_loops",),
            pass_criteria="reply lists at least two active open loops",
        ),
        StressCase(
            id="single_summarize_my_week",
            section="single_hop",
            query="summarize my week",
            expected_backends=("living_profile",),
            pass_criteria="reply cites situation brief content without fabrication",
        ),
        StressCase(
            id="single_what_did_i_tell_you_about_maya",
            section="single_hop",
            query="what did i tell you about maya last week",
            expected_backends=("supermemory",),
            pass_criteria="reply references a maya-related episode",
        ),
        StressCase(
            id="single_what_about_stripe",
            section="single_hop",
            query="what do i know about stripe",
            expected_backends=("graphiti",),
            pass_criteria="reply cites an entity or relation involving stripe",
        ),
    ]


def _multi_hop() -> list[StressCase]:
    return [
        StressCase(
            id="multi_meal_before_2pm",
            section="multi_hop",
            query="what did i eat before my 2pm yesterday",
            expected_backends=("calendar", "observations"),
            pass_criteria="reply identifies the meal and a time",
        ),
        StressCase(
            id="multi_spent_at_maya_places",
            section="multi_hop",
            query="how much have i spent at places maya recommended",
            expected_backends=("graphiti", "observations"),
            pass_criteria="reply joins maya to merchant and cites a total",
        ),
        StressCase(
            id="multi_board_meeting_attendees",
            section="multi_hop",
            query="who was at my last board meeting",
            expected_backends=("calendar", "graphiti"),
            pass_criteria="reply lists attendees inferred from the most recent board event",
        ),
        StressCase(
            id="multi_last_time_this_stressed",
            section="multi_hop",
            query="last time i was this stressed what was happening",
            expected_backends=("supermemory", "observations"),
            pass_criteria="reply gives a historical comparison with context",
        ),
        StressCase(
            id="multi_commitments_with_saurabh",
            section="multi_hop",
            query="what did i commit to in my last chat with saurabh",
            expected_backends=("graphiti", "chat_messages", "open_loops"),
            pass_criteria="reply cites the commitment",
        ),
        StressCase(
            id="multi_situation_right_now",
            section="multi_hop",
            query="what's my situation right now",
            expected_backends=("users.facts", "living_profile", "open_loops"),
            pass_criteria="reply composes user model + brief + today + open loops",
        ),
    ]


def _temporal() -> list[StressCase]:
    return [
        StressCase(
            id="temporal_today",
            section="temporal",
            query="what did i do today",
            expected_backends=("observations", "chat_messages"),
            pass_criteria="no yesterday bleed-through",
        ),
        StressCase(
            id="temporal_hour_ago",
            section="temporal",
            query="what happened an hour ago",
            expected_backends=("chat_messages", "observations"),
            pass_criteria="returns the most recent chat or observation",
        ),
        StressCase(
            id="temporal_last_monday_mood",
            section="temporal",
            query="last monday what was my mood",
            expected_backends=("observations",),
            pass_criteria="hits the correct date with TZ-aware bounds",
        ),
        StressCase(
            id="temporal_week_vs_week",
            section="temporal",
            query="compare this week to last week spending",
            expected_backends=("observations",),
            pass_criteria="two weekly totals bucketed on monday 00:00 local",
        ),
        StressCase(
            id="temporal_3_days_ago_ny",
            section="temporal",
            query="what did i do 3 days ago in new york",
            expected_backends=("observations", "chat_messages"),
            pass_criteria="period bounded by America/New_York not Asia/Singapore",
        ),
        StressCase(
            id="temporal_yesterday_logs",
            section="temporal",
            query="show me yesterday's logs",
            expected_backends=("observations",),
            pass_criteria="yesterday in current tz, no midnight overlap",
        ),
    ]


def _derivation() -> list[StressCase]:
    return [
        StressCase(
            id="derive_maya_company",
            section="derivation",
            query="what company does maya work at",
            expected_backends=("graphiti",),
            pass_criteria="reply says 'stripe' not 'i don't know'",
        ),
        StressCase(
            id="derive_recent_themes",
            section="derivation",
            query="what have i been thinking about lately",
            expected_backends=("supermemory",),
            pass_criteria="reply names 1-2 recurring themes",
        ),
        StressCase(
            id="derive_routine",
            section="derivation",
            query="what's my routine",
            expected_backends=("living_profile",),
            pass_criteria="reply names 1-2 habits with cadence",
        ),
        StressCase(
            id="derive_most_talked_to",
            section="derivation",
            query="who do i talk to most",
            expected_backends=("graphiti",),
            pass_criteria="reply names the most-connected entity",
        ),
        StressCase(
            id="derive_spending_delta",
            section="derivation",
            query="am i spending more than usual",
            expected_backends=("observations",),
            pass_criteria="reply quantifies delta versus a prior window",
        ),
    ]


def _correction() -> list[StressCase]:
    return [
        StressCase(
            id="correct_name_mid_chat",
            section="correction",
            query="btw it's kai not kay",
            pre_turn_messages=("hey kay, quick q",),
            expected_backends=("users.facts",),
            pass_criteria="users.facts.preferred_name updates in same turn",
        ),
        StressCase(
            id="correct_timezone",
            section="correction",
            query="actually i'm in new york for the week now",
            expected_backends=("users.timezone", "facts"),
            pass_criteria="timezone updated; next observation query uses new tz",
        ),
        StressCase(
            id="correct_resolve_loop",
            section="correction",
            query="ok confirmed dinner with maya for friday",
            expected_backends=("open_loops",),
            pass_criteria="corresponding loop transitions to resolved",
        ),
        StressCase(
            id="correct_third_party_name",
            section="correction",
            query="aayam is coming to the meeting too",
            pre_turn_messages=(),
            expected_backends=(),
            pass_criteria="users.facts.preferred_name is unchanged (aayam rejected)",
            notes="regression test for the Aayam fix",
        ),
        StressCase(
            id="correct_log_expense",
            section="correction",
            query="just spent 18 sgd on grab to the airport",
            expected_backends=("observations", "living_profile"),
            pass_criteria="observation logged; next turn's brief reflects it",
        ),
    ]


def _failure_injection() -> list[StressCase]:
    return [
        StressCase(
            id="fail_supermemory_timeout",
            section="failure_injection",
            query="what did i tell you about maya last week",
            expected_backends=("graphiti",),
            inject_failure="supermemory_timeout",
            pass_criteria="smart_recall returns graphiti-only; no silent zero",
        ),
        StressCase(
            id="fail_graphiti_down",
            section="failure_injection",
            query="what do i know about stripe",
            expected_backends=("supermemory",),
            inject_failure="graphiti_down",
            pass_criteria="smart_recall returns supermemory-only",
        ),
        StressCase(
            id="fail_postgres_slow",
            section="failure_injection",
            query="how much did i spend this week",
            expected_backends=(),
            inject_failure="postgres_slow",
            pass_criteria="reply says 'can't reach it' not '$0'",
        ),
        StressCase(
            id="fail_living_profile_empty",
            section="failure_injection",
            query="what's my situation right now",
            expected_backends=(),
            inject_failure="living_profile_empty",
            pass_criteria="USER MODEL skipped cleanly, no None leaks",
        ),
        StressCase(
            id="fail_calendar_sync_broken",
            section="failure_injection",
            query="what's on tomorrow",
            expected_backends=(),
            inject_failure="calendar_down",
            pass_criteria="reply indicates uncertain, brief flagged stale_or_uncertain",
        ),
    ]


def _voice_coherence() -> list[StressCase]:
    return [
        StressCase(
            id="voice_no_raw_tool_echo",
            section="voice_coherence",
            query="how much did i spend this week",
            expected_backends=("observations",),
            pass_criteria="no raw '- supermemory: ...' lines echoed",
        ),
        StressCase(
            id="voice_no_according_to_memory",
            section="voice_coherence",
            query="what do i know about stripe",
            expected_backends=("graphiti",),
            pass_criteria="reply avoids 'according to memory' / 'based on what i found'",
        ),
        StressCase(
            id="voice_numeric_uses_number",
            section="voice_coherence",
            query="how much have i spent on coffee",
            expected_backends=("observations",),
            pass_criteria="reply includes a specific number, not 'some'",
        ),
        StressCase(
            id="voice_single_source_on_conflict",
            section="voice_coherence",
            query="when is the board sync",
            expected_backends=("calendar",),
            pass_criteria="reply picks one source cleanly on conflict",
        ),
    ]
