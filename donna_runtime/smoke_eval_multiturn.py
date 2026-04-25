"""Multi-turn smoke eval — synthetic 3-day Donna conversation.

Unlike single-message fixtures in smoke_eval_fixtures.py, these exercise
cross-turn state: writes on day 1 must be recallable on day 2, open loops
tracked on day 2 must appear on day 3, etc.

Time is injected via `state["_injected_now"]` so the conversation replays
in its own wall-clock, independent of when the suite runs.

The runner drives `donna_turn` sequentially, feeding each turn's state to
the next. Assertions run per turn; cross-turn assertions run at the end.

Usage (live — requires real DB + ANTHROPIC_API_KEY + DONNA_E2E=1):
    DONNA_LIVE_EVAL=1 DONNA_E2E=1 python -m pytest \\
        tests/test_multiturn_smoke_eval.py -v -s
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TurnCategory = Literal[
    "voice",
    "tool_choice",
    "memory_write",
    "memory_recall",
    "widget",
    "mixed",
]


@dataclass(frozen=True)
class MultiTurn:
    """One turn inside a multi-turn fixture sequence."""
    turn_id: str
    at: str                              # ISO local time, injected as _injected_now
    message: str
    category: TurnCategory = "voice"
    expected_tools: tuple[str, ...] = ()
    banned_tools: tuple[str, ...] = ()
    expected_media: tuple[str, ...] = ()
    forbidden_media: tuple[str, ...] = ()
    max_reply_words: int = 120
    banned_phrases: tuple[str, ...] = (
        "I understand",
        "Great question",
        "AI assistant",
        "I'm here to help",
        "—",
        ";",
    )
    # Awareness expectations — what understanding should be implicit in this
    # turn even if no hard tool call is required. These are post-hoc human
    # checks against the JSONL output + DB state dump; they are not enforced
    # by the runner. The runner just makes them visible.
    should_catch: tuple[str, ...] = ()   # data/entity/fact she should register
    should_ignore: tuple[str, ...] = ()  # ambient content she should NOT log
    notes: str = ""


@dataclass(frozen=True)
class MultiTurnFixture:
    id: str
    user_id_prefix: str
    timezone: str
    turns: tuple[MultiTurn, ...]
    notes: str = ""
    # Canonical facts we'd expect the Living Profile to contain by the end of
    # the arc, and attention subjects we'd expect to have accrued weight.
    # These drive the post-arc state dump check, not per-turn assertions.
    expected_final_facts: tuple[str, ...] = ()
    expected_final_attention: tuple[str, ...] = ()


# ─────────────── Synthetic 3-day arc ───────────────
#
# Persona: startup founder prepping for Antler, lives in Mumbai (Asia/Kolkata),
# sleeps poorly, spends on coffee, juggling Sarah (offer) and Luca (deck review).
#
# Day 1 (Mon 2026-04-20) — scattered. Logs sleep, expense, mood; schedules a
# reminder; tracks an open loop about Sarah.
# Day 2 (Tue 2026-04-21) — consumes day 1. Spend recall, Sarah context, more
# sleep log, hard moment.
# Day 3 (Wed 2026-04-22) — reflection + cleanup. Multi-night recall, forgetting
# check, mood lookup, closing a loop.
THREE_DAY_ARC = MultiTurnFixture(
    id="three_day_arc",
    user_id_prefix="multiturn-3d",
    timezone="Asia/Kolkata",
    notes="Canonical 3-day arc covering all tool categories + cross-turn continuity.",
    turns=(
        # ───── Day 1, Monday ─────
        MultiTurn(
            turn_id="d1_morning_sleep",
            at="2026-04-20T08:42:00",
            message="morning. bad sleep again, like 4 hours",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="First sleep log of the arc. event_time should be last night.",
        ),
        MultiTurn(
            turn_id="d1_coffee_expense",
            at="2026-04-20T11:20:00",
            message="coffee was 6 bucks",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            banned_tools=("mcp__donna__track_open_loop",),
            notes="Countable expense. Must not track as open loop.",
        ),
        MultiTurn(
            turn_id="d1_sarah_loop",
            at="2026-04-20T14:15:00",
            message="meeting sarah at 4 to talk the offer, need to remember to circle back tomorrow",
            category="memory_write",
            expected_tools=("mcp__donna__track_open_loop",),
            notes="Untimed follow-up → track_open_loop for sarah offer.",
        ),
        MultiTurn(
            turn_id="d1_luca_reminder",
            at="2026-04-20T18:40:00",
            message="remind me to send luca the deck tomorrow at 9am",
            category="memory_write",
            expected_tools=("mcp__donna__schedule_reminder",),
            banned_tools=("mcp__donna__track_open_loop",),
            notes="Explicit time → schedule_reminder, not track_open_loop.",
        ),
        MultiTurn(
            turn_id="d1_mood_log",
            at="2026-04-20T21:10:00",
            message="mood's a 3 today",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="Numeric mood → log_observation.",
        ),

        # ───── Day 2, Tuesday ─────
        MultiTurn(
            turn_id="d2_spend_recall",
            at="2026-04-21T11:45:00",
            message="how much did i spend yesterday",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            banned_tools=("mcp__donna__recall_graph",),
            notes="Countable → tracker. Should find the $6 from day 1.",
        ),
        MultiTurn(
            turn_id="d2_sarah_context",
            at="2026-04-21T15:30:00",
            message="what did sarah say about the offer",
            category="memory_recall",
            expected_tools=("mcp__donna__recall_graph",),
            notes="Person + prior conversation → graph recall.",
        ),
        MultiTurn(
            turn_id="d2_sleep_log",
            at="2026-04-21T19:20:00",
            message="slept 5 hours last night",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="Second sleep log — day-over-day tracker material.",
        ),
        MultiTurn(
            turn_id="d2_crisis",
            at="2026-04-21T22:00:00",
            message="i think i want to quit. antler is too much",
            category="voice",
            banned_phrases=(
                "I understand", "Great question", "AI assistant",
                "I'm here to help", "—", ";",
                "I hear you", "that sounds",
            ),
            notes="Heavy moment. Acknowledge + useful; no empathy theater.",
        ),

        # ───── Day 3, Wednesday ─────
        MultiTurn(
            turn_id="d3_sleep_week",
            at="2026-04-22T08:30:00",
            message="how's my sleep been the last 3 nights",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes="Multi-day tracker read. Should see both 4h and 5h from day 1+2.",
        ),
        MultiTurn(
            turn_id="d3_forgetting_check",
            at="2026-04-22T10:15:00",
            message="what am i forgetting",
            category="memory_recall",
            expected_tools=("mcp__donna__list_open_loops",),
            notes="Generic 'what am i forgetting' → list_open_loops. Should see sarah.",
        ),
        MultiTurn(
            turn_id="d3_mood_recall",
            at="2026-04-22T14:45:00",
            message="what was my mood on monday",
            category="memory_recall",
            expected_tools=(
                "mcp__donna__resolve_time_expression",
                "mcp__donna__read_tracker",
            ),
            notes="Time + tracker composition. Resolve 'monday' then query tracker.",
        ),
        MultiTurn(
            turn_id="d3_close_loop",
            at="2026-04-22T17:00:00",
            message="moved the sarah follow-up to friday",
            category="memory_write",
            expected_tools=(
                "mcp__donna__list_open_loops",
                "mcp__donna__close_open_loop",
            ),
            notes="Resolves the day-1 loop. Find it first, then close.",
        ),
    ),
)


# ─────────────── Write-saturation → read-probe arc ───────────────
#
# Purpose: stress-test write routing and read synthesis. Day 1+2 saturate
# the memory backends with ~15 writes across every category. Day 3 probes
# reads across every reasoning shape — direct aggregation, period
# comparison, specific item, type-mixing, person recall, vague asks,
# synthesis. For each read, inspect: which tools did she pick, in what
# order, did the answer numerically match the writes?
#
# Persona: same founder. Mumbai (Asia/Kolkata).
WRITE_HEAVY_READ_PROBE = MultiTurnFixture(
    id="write_heavy_read_probe",
    user_id_prefix="writeheavy",
    timezone="Asia/Kolkata",
    notes=(
        "Stress test — ~15 writes across 2 days, then ~10 reads covering "
        "direct aggregation, period comparison, type mixing, synthesis. "
        "Inspect tool choice + answer accuracy per read."
    ),
    turns=(
        # ──── Day 1 (Mon 2026-04-20) — write saturation part 1 ────
        MultiTurn(
            turn_id="w_d1_coffee1",
            at="2026-04-20T08:15:00",
            message="morning coffee, 5 bucks",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="1st expense of the week.",
        ),
        MultiTurn(
            turn_id="w_d1_sleep",
            at="2026-04-20T08:20:00",
            message="slept 6 hours last night",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d1_lunch",
            at="2026-04-20T13:45:00",
            message="lunch was 180 rupees",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d1_open_loop_luca",
            at="2026-04-20T16:00:00",
            message="need to send luca the deck this week",
            category="memory_write",
            expected_tools=("mcp__donna__track_open_loop",),
            banned_tools=("mcp__donna__schedule_reminder",),
            notes="Untimed → open loop, not reminder.",
        ),
        MultiTurn(
            turn_id="w_d1_reminder_antler",
            at="2026-04-20T17:30:00",
            message="remind me about the antler call thursday 4pm",
            category="memory_write",
            expected_tools=("mcp__donna__schedule_reminder",),
            notes="Explicit time → schedule_reminder.",
        ),
        MultiTurn(
            turn_id="w_d1_coffee2",
            at="2026-04-20T19:00:00",
            message="another coffee, 6 bucks",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="2nd coffee same day. Idempotency guard should NOT block (different amount).",
        ),
        MultiTurn(
            turn_id="w_d1_mood",
            at="2026-04-20T21:30:00",
            message="mood's a 2 tonight, drained",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),

        # ──── Day 2 (Tue 2026-04-21) — write saturation part 2 ────
        MultiTurn(
            turn_id="w_d2_sleep",
            at="2026-04-21T08:10:00",
            message="only 4 hours sleep",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d2_coffee",
            at="2026-04-21T09:30:00",
            message="coffee 5 bucks",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d2_no_write_feelings",
            at="2026-04-21T11:00:00",
            message="feeling scattered today, brain fog",
            category="memory_write",
            banned_tools=("mcp__donna__log_observation",),
            notes="Vague feeling, no number → do NOT log.",
        ),
        MultiTurn(
            turn_id="w_d2_sarah_loop",
            at="2026-04-21T13:00:00",
            message="sarah wants an answer on the term sheet by friday",
            category="memory_write",
            expected_tools=("mcp__donna__track_open_loop",),
            notes="Deadline-bearing commitment → open loop.",
        ),
        MultiTurn(
            turn_id="w_d2_gas",
            at="2026-04-21T15:45:00",
            message="uber to the airport, 350 rupees",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d2_exercise",
            at="2026-04-21T18:00:00",
            message="ran 3k today",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            notes="Exercise observation with distance.",
        ),
        MultiTurn(
            turn_id="w_d2_mood",
            at="2026-04-21T22:15:00",
            message="mood 4, antler went okay",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
        ),
        MultiTurn(
            turn_id="w_d2_reminder_gym",
            at="2026-04-21T23:00:00",
            message="wake me at 6am tomorrow for the gym",
            category="memory_write",
            expected_tools=("mcp__donna__schedule_reminder",),
        ),

        # ──── Day 3 (Wed 2026-04-22) — read probe day ────
        MultiTurn(
            turn_id="r_direct_aggregation",
            at="2026-04-22T08:00:00",
            message="what did i spend in total these last two days",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes=(
                "Direct aggregation across explicit period. Should read_tracker "
                "with period spanning monday+tuesday. Expect sum near the written "
                "values (5+180+6 on mon, 5+350 on tue in mixed currencies — see "
                "if she flags unit mismatch)."
            ),
        ),
        MultiTurn(
            turn_id="r_period_compare",
            at="2026-04-22T09:10:00",
            message="am i spending more today than monday",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes="Period comparison. She should pull both periods. No day-3 expenses yet → answer should reflect zero.",
        ),
        MultiTurn(
            turn_id="r_specific_item",
            at="2026-04-22T10:00:00",
            message="what was my first coffee cost",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes="Specific item recall. Expect $5 (first logged was monday 8:15).",
        ),
        MultiTurn(
            turn_id="r_sleep_pattern",
            at="2026-04-22T10:45:00",
            message="how's my sleep been this week",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes="Pattern recall — should see 6h mon, 4h tue. Answer should name both.",
        ),
        MultiTurn(
            turn_id="r_mixed_sleep_mood",
            at="2026-04-22T11:30:00",
            message="is my mood tracking with my sleep this week",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes=(
                "Type-mixing synthesis. Should correlate sleep (6h,4h) with mood "
                "(2,4). Needs two tracker reads or one tracker read over all types. "
                "Stresses model's synthesis ability, not just tool choice."
            ),
        ),
        MultiTurn(
            turn_id="r_person_context",
            at="2026-04-22T12:00:00",
            message="what was sarah's ask again",
            category="memory_recall",
            expected_tools=("mcp__donna__recall_graph",),
            notes="Person-centric recall. Should find 'term sheet by friday' from day 2.",
        ),
        MultiTurn(
            turn_id="r_vague_forgetting",
            at="2026-04-22T13:30:00",
            message="what am i forgetting",
            category="memory_recall",
            expected_tools=("mcp__donna__list_open_loops",),
            notes="Should surface luca deck + sarah term sheet (both tracked).",
        ),
        MultiTurn(
            turn_id="r_time_resolve_and_read",
            at="2026-04-22T14:45:00",
            message="what did i log on monday",
            category="memory_recall",
            expected_tools=(
                "mcp__donna__resolve_time_expression",
                "mcp__donna__read_tracker",
            ),
            notes=(
                "Time + tracker composition. 'Monday' must resolve to day 1 range, "
                "then tracker read scoped to that range."
            ),
        ),
        MultiTurn(
            turn_id="r_speculation",
            at="2026-04-22T16:00:00",
            message="should i be worried about my spending",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            notes=(
                "Speculative/judgment. Needs tracker read + interpretation. Donna "
                "should take a position, not hedge."
            ),
        ),
        MultiTurn(
            turn_id="r_synthesis",
            at="2026-04-22T18:00:00",
            message="give me a 2-line summary of my week so far",
            category="memory_recall",
            notes=(
                "Synthesis. Multiple tools likely: tracker + open_loops + graph. "
                "Test whether she picks a coherent set or just one."
            ),
        ),
    ),
)


# ─────────────── Awareness arc — messy, voice-forward texting ───────────────
#
# Purpose: stress situational awareness, not tool routing. Real texting is
# 80% ambient (jokes, vents, tangents) and 20% substantive data buried in
# voice. This fixture tests whether Donna can:
#
#   (a) SKIP ambient without logging garbage
#   (b) CATCH the data/identity/relationship signals buried in voice
#   (c) BUILD the Living Profile across turns (who the user is)
#   (d) BUILD attention weights on the subjects that actually matter
#   (e) RESPOND in-register to the user's voice, not corporate-flatten it
#
# Per-turn assertions stay light — too-strict `expected_tools` would be
# wrong for a test about *judgment*. Instead, each turn carries
# `should_catch` and `should_ignore` notes that are post-hoc human checks
# against the JSONL trace + final DB state dump.
#
# Persona: Arnav in Mumbai. Founder, Antler cohort, prepping a pitch deck.
# Lives in the cafe, works with Luca and Sarah, has a sister Sanj. Procrastinates.
# Knows it. Sonnet should pick up on all of that by the end.
AWARENESS_ARC = MultiTurnFixture(
    id="awareness_arc",
    user_id_prefix="awareness",
    timezone="Asia/Kolkata",
    notes=(
        "Messy 3-day texting arc. Tests situational awareness: catching "
        "buried data, building the Living Profile, tracking attention, "
        "mirroring voice. Turn-level assertions are soft; post-hoc JSONL "
        "and DB state dump are the real signal."
    ),
    expected_final_facts=(
        "profession: founder / entrepreneur",
        "current_program: Antler",
        "home_city: Mumbai (Asia/Kolkata)",
        "regular_cafe: yes (frequents same place, known by barista)",
        "work_relationships: Luca (deck collaborator), Sarah (term-sheet counterpart)",
        "family: sister named Sanj",
        "self_perception: aware of own procrastination; 'triages' now",
        "preferred_food: chole bhature",
        "habits: gym (aspirational — skipped once), coffee heavy (3+/day)",
    ),
    expected_final_attention=(
        "antler (active program, deadlines)",
        "sarah term sheet (friday deadline)",
        "luca deck (thursday delivery)",
        "pitch deck slide 7 (user self-doubt)",
        "sleep + mood correlation (low mood days correlate with low sleep)",
    ),
    turns=(
        # ──── Day 1 (Mon 2026-04-20) — groggy start, messy day ────
        MultiTurn(
            turn_id="a_d1_01_ugh",
            at="2026-04-20T07:12:00",
            message="ughhhhh",
            category="voice",
            max_reply_words=6,
            banned_tools=("mcp__donna__log_observation", "mcp__donna__track_open_loop"),
            should_ignore=("pure ambient — no log, no track, just a minimal ack",),
            notes="Opening vibe. Any tool call is wrong.",
        ),
        MultiTurn(
            turn_id="a_d1_02_sleep_buried",
            at="2026-04-20T07:15:00",
            message="ok 5h sleep wth",
            category="memory_write",
            should_catch=("sleep=5h, event_time=last night",),
            notes=(
                "Buried sleep data in casual voice. She SHOULD log_observation "
                "but with minimal narration back. A verbose 'noted you slept 5h...' "
                "is wrong-shaped."
            ),
        ),
        MultiTurn(
            turn_id="a_d1_03_dentist_vent",
            at="2026-04-20T07:42:00",
            message="bro i cant believe the dentist called again after i said next week",
            category="voice",
            should_catch=(
                "relational: user has a dentist (low-priority entity)",
                "stance: user feels intruded on — don't moralize the dentist",
            ),
            should_ignore=("not a log, not a loop — it's a vent",),
            notes="Vent. She may track an open loop loosely (dentist follow-up) but not required.",
        ),
        MultiTurn(
            turn_id="a_d1_04_tangent",
            at="2026-04-20T09:00:00",
            message="which is better coconut water or electrolyte powder",
            category="voice",
            banned_tools=(
                "mcp__donna__log_observation",
                "mcp__donna__track_open_loop",
                "mcp__donna__schedule_reminder",
            ),
            should_catch=("user values hydration / health (soft fact)",),
            should_ignore=("NOT a log. A tangent question.",),
            notes="Tangent question — she should take a position, not hedge or list pros/cons at length.",
        ),
        MultiTurn(
            turn_id="a_d1_05_coffee_identity",
            at="2026-04-20T10:30:00",
            message="morning coffee happened. 6 bucks. killer barista tho she remembered my order",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=(
                "expense=6, type=coffee",
                "semantic: user is a regular at a specific cafe (barista knows order)",
            ),
            notes=(
                "Expense with identity signal buried. Log the money; the cafe-regular "
                "fact should end up in Living Profile via extract_user_facts hook."
            ),
        ),
        MultiTurn(
            turn_id="a_d1_06_sanj",
            at="2026-04-20T12:15:00",
            message="sanj is back in town this weekend",
            category="memory_write",
            should_catch=(
                "person: Sanj (likely family / close)",
                "event: returning this weekend (soft calendar/attention)",
            ),
            notes="Relational fact. graph ingest should pick up Sanj.",
        ),
        MultiTurn(
            turn_id="a_d1_07_self_aware",
            at="2026-04-20T14:00:00",
            message="just spent 30 min doomscrolling. why am i like this",
            category="voice",
            banned_tools=("mcp__donna__log_observation",),
            should_catch=(
                "self-perception: user sees themselves as a procrastinator",
                "mood signal: frustrated at self",
            ),
            should_ignore=(
                "30 min doomscrolling is NOT a countable habit log — it's a vent",
            ),
            notes=(
                "Classic self-deprecating vent. Do not 'log doomscrolling as 30 min'. "
                "Do not moralize. One dry line back."
            ),
        ),
        MultiTurn(
            turn_id="a_d1_08_antler_mention",
            at="2026-04-20T15:20:00",
            message="antler on thursday 4pm btw",
            category="memory_write",
            should_catch=("event: Antler thursday 4pm",),
            notes=(
                "Already tracked via reminder ideally. If she re-schedules, fine. "
                "If she says 'already have that', even better — shows continuity."
            ),
        ),
        MultiTurn(
            turn_id="a_d1_09_lunch_food_identity",
            at="2026-04-20T17:45:00",
            message="lunch was 220 rs, chole bhature, worth it",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=(
                "expense=220 INR",
                "food preference: chole bhature",
                "voice signal: 'worth it' — user is frugal-ish, reflects on spend",
            ),
            notes="Expense + food preference. Log expense; food preference is a soft fact for Living Profile.",
        ),
        MultiTurn(
            turn_id="a_d1_10_sarah_deadline",
            at="2026-04-20T19:00:00",
            message="sarah asked about the term sheet. said friday",
            category="memory_write",
            expected_tools=("mcp__donna__track_open_loop",),
            should_catch=(
                "commitment: sarah expects answer by friday",
                "person: Sarah (business, likely investor/acquirer)",
            ),
            notes="Deadline open loop. Sarah already in graph from prior arcs.",
        ),
        MultiTurn(
            turn_id="a_d1_11_identity_evolution",
            at="2026-04-20T21:30:00",
            message="you know what's funny, a year ago i'd have said yes to anything. now i triage",
            category="voice",
            banned_tools=("mcp__donna__log_observation",),
            should_catch=(
                "self-perception: user has evolved — more selective, boundaries",
                "fits Living Profile: growth-oriented, self-observing",
            ),
            notes=(
                "Pure identity signal. Not a log. This is Living Profile food — the "
                "extract_user_facts hook should notice 'user triages now'."
            ),
        ),
        MultiTurn(
            turn_id="a_d1_12_end_day",
            at="2026-04-20T22:45:00",
            message="mood 3. bad brain. night",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=("mood=3, sign-off",),
            max_reply_words=8,
            notes="Sign-off. Log mood, don't lecture, match the register.",
        ),

        # ──── Day 2 (Tue 2026-04-21) — mid-prep ────
        MultiTurn(
            turn_id="a_d2_01_good_sleep",
            at="2026-04-21T08:30:00",
            message="slept 7 hours what a luxury",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=("sleep=7h + user's voice: treats 7h as luxury (implies baseline low)",),
            notes="Log + should maybe call this out vs the 5h yesterday. Continuity win.",
        ),
        MultiTurn(
            turn_id="a_d2_02_ambient",
            at="2026-04-21T09:15:00",
            message="k gm",
            category="voice",
            banned_tools=(
                "mcp__donna__log_observation",
                "mcp__donna__smart_recall",
                "mcp__donna__read_tracker",
            ),
            max_reply_words=3,
            should_ignore=("pure ambient greeting",),
            notes="Any tool call is wrong.",
        ),
        MultiTurn(
            turn_id="a_d2_03_term_sheet_detail",
            at="2026-04-21T10:00:00",
            message="ok so the term sheet — 20% equity, 2 yr vest, no accel. thoughts",
            category="voice",
            should_catch=(
                "sarah term sheet numbers: 20% equity, 2yr vest, no acceleration",
                "user wants her actual take — not a menu of options",
            ),
            notes=(
                "Seeking input. She should TAKE A POSITION on 20% + 2yr + no accel. "
                "Graph ingest should capture the numbers."
            ),
        ),
        MultiTurn(
            turn_id="a_d2_04_luca_update",
            at="2026-04-21T11:30:00",
            message="lol luca texted back. he's in.",
            category="memory_write",
            should_catch=(
                "luca situation progressed — relationship/commitment update",
                "may want to close or update the luca deck open loop",
            ),
            notes=(
                "Status update on a prior open loop. Ideally track_open_loop or "
                "a note; at minimum graph ingest sees 'luca is in'."
            ),
        ),
        MultiTurn(
            turn_id="a_d2_05_lunch_shorter",
            at="2026-04-21T13:00:00",
            message="lunch same place, 220",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=(
                "expense=220, same cafe as yesterday (pattern reinforcement)",
                "voice: extremely terse — she's trusting Donna to infer",
            ),
            max_reply_words=6,
            notes="Short-form log. She should match register. No 'got it, logged 220 rupees for lunch at your usual spot.'",
        ),
        MultiTurn(
            turn_id="a_d2_06_deck_doubt",
            at="2026-04-21T15:45:00",
            message="the pitch deck is not landing slide 7. cut it?",
            category="voice",
            should_catch=(
                "user has a pitch deck, slide 7 is struggling",
                "decision ask — she should commit, not hedge",
            ),
            notes="Take a position. Attention should grow on 'pitch deck / slide 7'.",
        ),
        MultiTurn(
            turn_id="a_d2_07_coffee_playful",
            at="2026-04-21T17:20:00",
            message="coffee no 3 dont judge",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=(
                "expense: another coffee",
                "voice: playful / self-aware habit",
                "identity: 3+ coffees/day is a pattern",
            ),
            should_ignore=("don't moralize caffeine intake",),
            max_reply_words=10,
            notes="Playful log. One-line reply with wit, or just log and ack.",
        ),
        MultiTurn(
            turn_id="a_d2_08_gym_skipped",
            at="2026-04-21T19:00:00",
            message="running late to gym, skipping",
            category="voice",
            should_catch=(
                "habit signal: gym matters (at least aspirationally)",
                "event: skipped today",
            ),
            should_ignore=(
                "not a log (no number). Not a reminder. Not an open loop.",
            ),
            notes="Ambient status. Maybe track it softly or do nothing. No log_observation.",
        ),
        MultiTurn(
            turn_id="a_d2_09_vent_uber",
            at="2026-04-21T20:30:00",
            message="the uber driver literally did not move for 10 minutes what",
            category="voice",
            banned_tools=(
                "mcp__donna__log_observation",
                "mcp__donna__track_open_loop",
            ),
            should_ignore=("vent — no data, no action required",),
            max_reply_words=10,
            notes="Pure vent. One dry line. No tool calls.",
        ),
        MultiTurn(
            turn_id="a_d2_10_end_day",
            at="2026-04-21T22:00:00",
            message="mood 4, shaky but okay",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=("mood=4 + 'shaky' qualitative note",),
            max_reply_words=8,
            notes="Sign-off log. Note 'shaky' doesn't go into the numeric fields but could go in raw.",
        ),

        # ──── Day 3 (Wed 2026-04-22) — reflection + surfacing ────
        MultiTurn(
            turn_id="a_d3_01_open_day",
            at="2026-04-22T08:00:00",
            message="so what's on my plate today",
            category="memory_recall",
            expected_tools=("mcp__donna__list_open_loops",),
            should_catch=(
                "open loops: luca deck, sarah term sheet (both tracked)",
                "calendar: antler thursday (already scheduled)",
            ),
            notes=(
                "Open-ended planning question. Should surface both tracked loops + "
                "upcoming calendar. Maybe 2 tool calls (list_open_loops + list_calendar)."
            ),
        ),
        MultiTurn(
            turn_id="a_d3_02_coffee_spending",
            at="2026-04-22T09:15:00",
            message="how's my coffee spending been",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            should_catch=(
                "should reference multiple coffee logs from mon+tue",
                "pattern: 3+ coffees/day — worth noting or not (judgment)",
            ),
            notes="Tracker aggregation. Should sum or list.",
        ),
        MultiTurn(
            turn_id="a_d3_03_sarah_weird",
            at="2026-04-22T10:30:00",
            message="remind me why sarah's offer felt weird",
            category="memory_recall",
            expected_tools=("mcp__donna__recall_graph",),
            should_catch=(
                "should surface the 20% / 2yr / no-accel numbers from day 2",
                "connect to user's own 'now i triage' framing if she's aware",
            ),
            notes=(
                "Person-centric recall. Should find the term sheet numbers AND "
                "ideally the user's own triage stance. Rare synthesis win if she does."
            ),
        ),
        MultiTurn(
            turn_id="a_d3_04_predictable",
            at="2026-04-22T12:00:00",
            message="i'm at the cafe again. how predictable",
            category="voice",
            should_catch=("reinforces the regular-at-cafe semantic fact",),
            should_ignore=("not a log; just voice",),
            max_reply_words=10,
            notes="Self-aware identity. Dry reply. No logging.",
        ),
        MultiTurn(
            turn_id="a_d3_05_deck_slipping",
            at="2026-04-22T13:45:00",
            message="i don't think i can ship the deck by thursday",
            category="memory_write",
            should_catch=(
                "deadline risk: luca deck (thursday) is slipping",
                "emotional undertone: overwhelm — don't dismiss",
                "should probably update/flag the open loop",
            ),
            notes=(
                "Major status update. She should NOT chirp 'you got this!' She "
                "should flag it — the thursday deadline is now at risk. Ideally "
                "track_open_loop update or flag_attention (if tool existed)."
            ),
        ),
        MultiTurn(
            turn_id="a_d3_06_retrospective",
            at="2026-04-22T15:00:00",
            message="what have i been doing all week lol",
            category="memory_recall",
            should_catch=(
                "summary should reference: deck work, coffee pattern, sleep "
                "variance, sarah+luca, mood swings, Antler thursday",
            ),
            notes=(
                "Open retrospective. True synthesis — tracker + open_loops + "
                "graph + calendar combined. Tests her ability to compose an answer."
            ),
        ),
        MultiTurn(
            turn_id="a_d3_07_memory_check",
            at="2026-04-22T17:30:00",
            message="wait did i log the uber yesterday",
            category="memory_recall",
            expected_tools=("mcp__donna__read_tracker",),
            should_catch=(
                "truth: user did NOT log the uber — the 'uber driver did not move' "
                "was a vent, not a log. She should say 'no, you just vented about "
                "the driver' — NOT fabricate a log.",
            ),
            notes=(
                "Adversarial. Trap — user thinks they logged it; they didn't. "
                "If Donna confirms 'yes, logged', she's hallucinating. She should "
                "check tracker, find no row, and say so."
            ),
        ),
        MultiTurn(
            turn_id="a_d3_08_sanj_mood",
            at="2026-04-22T20:00:00",
            message="sanj landed. going out. mood 5 finally",
            category="memory_write",
            expected_tools=("mcp__donna__log_observation",),
            should_catch=(
                "mood=5 (peak of the week)",
                "continuity: sanj arrival was foreshadowed day 1",
                "attention/pattern: mood lifting correlates with sanj + social",
            ),
            notes=(
                "Closing beat. Log mood. Ideally acknowledge continuity: 'sanj is "
                "here like you said she would be.' Feels human when she does that."
            ),
        ),
    ),
)


# ─────────────── Timezone propagation arc ───────────────
#
# Purpose: exercise the bitemporal facts wiring for timezone writes.
# Turn 1 sets the operational tz. Turn 2 probes the rendered profile for
# that value. Turn 3 changes it, which should close the first bitemporal
# row and open a second. Post-arc DB state dump is the real signal:
# list_history(predicate="current_timezone") should return two rows, the
# older one with t_valid_to closed.
TIMEZONE_PROPAGATION_ARC = MultiTurnFixture(
    id="timezone_propagation",
    user_id_prefix="tz-arc",
    timezone="Asia/Singapore",
    notes=(
        "Timezone write → readback → correction. Verifies set_timezone "
        "mirrors into the bitemporal facts table and that the second write "
        "updates (not supersedes) the belief."
    ),
    expected_final_facts=(
        "current_timezone: America/New_York (after the correction)",
        "bitemporal history: 2 rows — Asia/Singapore closed, America/New_York open",
    ),
    turns=(
        MultiTurn(
            turn_id="tz_01_set_ny",
            at="2026-04-22T09:00:00",
            message="actually my timezone is America/New_York",
            category="memory_write",
            expected_tools=("mcp__donna__set_timezone",),
            should_catch=(
                "operational tz updated to NYC",
                "bitemporal Fact(predicate=current_timezone, object=America/New_York) recorded",
            ),
            notes="First write. Should insert the initial bitemporal row.",
        ),
        MultiTurn(
            turn_id="tz_02_confirm",
            at="2026-04-22T09:05:00",
            message="what timezone do you have for me",
            category="memory_recall",
            banned_tools=(
                "mcp__donna__recall_graph",
                "mcp__donna__recall_episodic",
            ),
            should_catch=(
                "reply mentions New York / Eastern / America/New_York",
            ),
            max_reply_words=20,
            notes=(
                "Readback. The rendered user model already has the tz, so "
                "no tool call is strictly needed — answering from context is "
                "fine. Recall tools would be wrong."
            ),
        ),
        MultiTurn(
            turn_id="tz_03_correct_back",
            at="2026-04-22T15:00:00",
            message="wait scratch that, back to Asia/Singapore",
            category="memory_write",
            expected_tools=("mcp__donna__set_timezone",),
            should_catch=(
                "bitemporal update: NY row closed (t_valid_to set), SG row opened",
                "list_history should now return 2 rows for predicate=current_timezone",
            ),
            notes=(
                "Second write — a state change, not a correction. This is "
                "the crucial bitemporal assertion: update_fact, not "
                "supersede_fact. Post-arc DB dump confirms the two-row history."
            ),
        ),
    ),
)


ALL_MULTITURN_FIXTURES: tuple[MultiTurnFixture, ...] = (
    THREE_DAY_ARC,
    WRITE_HEAVY_READ_PROBE,
    AWARENESS_ARC,
    TIMEZONE_PROPAGATION_ARC,
)
