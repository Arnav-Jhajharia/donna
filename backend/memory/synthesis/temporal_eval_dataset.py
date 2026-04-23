"""Expanded synthetic temporal-memory eval dataset.

The scenarios are intentionally deterministic and hand-labeled. They cover
different user types, timezones, and memory shapes without requiring external
datasets or paid model calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.memory.synthesis.temporal_brief import StressCase, TemporalEvidence, TemporalItem

EVAL_NOW = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Archetype:
    id: str
    timezone: str
    fact_key: str
    fact_value: str
    last_week: str
    this_week: str
    next_week: str
    open_loop: str
    observation: str
    expected_terms: tuple[str, ...]
    current_terms: tuple[str, ...]
    last_week_terms: tuple[str, ...]
    next_week_terms: tuple[str, ...]
    stale_terms: tuple[str, ...] = ()


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        id="founder_fundraising",
        timezone="Asia/Singapore",
        fact_key="profession",
        fact_value="startup founder",
        last_week="last week the seed deck was still messy and the model slide was weak",
        this_week="this week the priority is investor updates and Donna memory architecture",
        next_week="partner meeting with Mira about the seed round",
        open_loop="send investor update draft",
        observation="mood focused before investor prep",
        expected_terms=("deck", "model", "investor", "Mira"),
        current_terms=("investor", "Donna"),
        last_week_terms=("deck", "model"),
        next_week_terms=("Mira", "seed"),
    ),
    Archetype(
        id="grad_student",
        timezone="America/New_York",
        fact_key="profession",
        fact_value="grad student",
        last_week="last week the lab report and literature review slipped",
        this_week="this week algorithms midterm and thesis outline are the focus",
        next_week="meeting supervisor Dr Chen about thesis scope",
        open_loop="finish thesis outline",
        observation="sleep 5.5 hours before algorithms revision",
        expected_terms=("lab", "literature", "algorithms", "thesis", "Chen"),
        current_terms=("algorithms", "thesis"),
        last_week_terms=("lab", "literature"),
        next_week_terms=("Chen", "scope"),
    ),
    Archetype(
        id="parent_caregiver",
        timezone="Europe/London",
        fact_key="household",
        fact_value="parent with school-age child",
        last_week="last week school forms and the pediatrician follow-up were pending",
        this_week="this week childcare pickup logistics are the main constraint",
        next_week="parent teacher conference on reading progress",
        open_loop="submit school trip consent form",
        observation="expense school uniform 42 GBP",
        expected_terms=("school", "pediatrician", "childcare", "teacher"),
        current_terms=("childcare", "pickup"),
        last_week_terms=("forms", "pediatrician"),
        next_week_terms=("teacher", "reading"),
    ),
    Archetype(
        id="sales_manager",
        timezone="America/Los_Angeles",
        fact_key="profession",
        fact_value="sales manager",
        last_week="last week QBR prep and renewal risk for Acme were the big items",
        this_week="this week pipeline review and Acme renewal calls are active",
        next_week="onsite negotiation with Acme procurement",
        open_loop="send revised Acme pricing",
        observation="mood anxious before pipeline review",
        expected_terms=("QBR", "renewal", "Acme", "pipeline", "procurement"),
        current_terms=("pipeline", "Acme"),
        last_week_terms=("QBR", "renewal"),
        next_week_terms=("procurement", "negotiation"),
    ),
    Archetype(
        id="freelancer_budget",
        timezone="Asia/Kolkata",
        fact_key="profession",
        fact_value="freelance designer",
        last_week="last week the Vega invoice was unpaid and revisions dragged",
        this_week="this week client revisions and cashflow are the pressure points",
        next_week="tax payment deadline and Vega final handoff",
        open_loop="chase Vega invoice",
        observation="expense software subscription 29 USD",
        expected_terms=("Vega", "invoice", "revisions", "cashflow", "tax"),
        current_terms=("revisions", "cashflow"),
        last_week_terms=("invoice", "unpaid"),
        next_week_terms=("tax", "handoff"),
    ),
    Archetype(
        id="health_habits",
        timezone="Australia/Sydney",
        fact_key="life_stage",
        fact_value="rebuilding routines",
        last_week="last week coffee daily and late nights were normal",
        this_week="this week no caffeine and sleep consistency are the goals",
        next_week="physio appointment for shoulder mobility",
        open_loop="protect sleep schedule",
        observation="sleep 7.5 hours",
        expected_terms=("coffee", "caffeine", "sleep", "physio"),
        current_terms=("caffeine", "sleep"),
        last_week_terms=("coffee", "late"),
        next_week_terms=("physio", "shoulder"),
        stale_terms=("coffee daily",),
    ),
    Archetype(
        id="athlete_training",
        timezone="Europe/Berlin",
        fact_key="life_stage",
        fact_value="marathon training",
        last_week="last week long run was 24km and calves felt tight",
        this_week="this week taper and mobility work matter more than volume",
        next_week="half marathon race weekend",
        open_loop="book sports massage",
        observation="exercise easy run 7km",
        expected_terms=("24km", "calves", "taper", "mobility", "race"),
        current_terms=("taper", "mobility"),
        last_week_terms=("24km", "calves"),
        next_week_terms=("race", "marathon"),
    ),
    Archetype(
        id="job_seeker",
        timezone="America/Chicago",
        fact_key="profession",
        fact_value="job seeker",
        last_week="last week portfolio rewrite and recruiter intro were incomplete",
        this_week="this week interview prep and take-home project are active",
        next_week="onsite interview with Northstar",
        open_loop="send recruiter availability",
        observation="mood nervous before take-home review",
        expected_terms=("portfolio", "recruiter", "interview", "Northstar"),
        current_terms=("interview", "take-home"),
        last_week_terms=("portfolio", "recruiter"),
        next_week_terms=("onsite", "Northstar"),
    ),
    Archetype(
        id="immigration_admin",
        timezone="Asia/Dubai",
        fact_key="current_city",
        fact_value="Dubai",
        last_week="last week visa forms and bank statement collection were blocking",
        this_week="this week biometrics appointment and embassy checklist matter",
        next_week="visa interview at the embassy",
        open_loop="print bank statements",
        observation="expense visa photos 18 AED",
        expected_terms=("visa", "bank", "biometrics", "embassy"),
        current_terms=("biometrics", "checklist"),
        last_week_terms=("forms", "bank"),
        next_week_terms=("interview", "embassy"),
    ),
    Archetype(
        id="creator_launch",
        timezone="America/New_York",
        fact_key="profession",
        fact_value="video creator",
        last_week="last week script edits and thumbnail concepts were stuck",
        this_week="this week sponsor read and launch edit are active",
        next_week="video launch and sponsor performance report",
        open_loop="approve final thumbnail",
        observation="mood excited after rough cut",
        expected_terms=("script", "thumbnail", "sponsor", "launch"),
        current_terms=("sponsor", "edit"),
        last_week_terms=("script", "thumbnail"),
        next_week_terms=("launch", "performance"),
    ),
    Archetype(
        id="exec_ops",
        timezone="America/New_York",
        fact_key="profession",
        fact_value="operations executive",
        last_week="last week board memo and hiring plan were late",
        this_week="this week board prep and headcount tradeoffs are active",
        next_week="leadership offsite on operating cadence",
        open_loop="finalize hiring plan",
        observation="mood tense before board prep",
        expected_terms=("board", "hiring", "headcount", "offsite"),
        current_terms=("board", "headcount"),
        last_week_terms=("memo", "hiring"),
        next_week_terms=("offsite", "cadence"),
    ),
    Archetype(
        id="remote_traveler",
        timezone="Asia/Tokyo",
        fact_key="current_city",
        fact_value="Tokyo",
        last_week="last week hotel wifi was unreliable and passport copy was missing",
        this_week="this week coworking setup and client timezone overlap are the issue",
        next_week="flight to Seoul and client workshop",
        open_loop="upload passport copy",
        observation="expense coworking day pass 2500 JPY",
        expected_terms=("hotel", "passport", "coworking", "Seoul", "workshop"),
        current_terms=("coworking", "timezone"),
        last_week_terms=("wifi", "passport"),
        next_week_terms=("Seoul", "workshop"),
    ),
    Archetype(
        id="researcher",
        timezone="Europe/Paris",
        fact_key="profession",
        fact_value="research scientist",
        last_week="last week paper rebuttal and baseline experiments were unfinished",
        this_week="this week ablations and reviewer response are the main work",
        next_week="conference talk dry run",
        open_loop="rerun baseline experiments",
        observation="sleep 6 hours after ablations",
        expected_terms=("rebuttal", "baseline", "ablations", "conference"),
        current_terms=("ablations", "reviewer"),
        last_week_terms=("rebuttal", "baseline"),
        next_week_terms=("conference", "talk"),
    ),
    Archetype(
        id="elder_care",
        timezone="America/New_York",
        fact_key="household",
        fact_value="helps with elder care",
        last_week="last week insurance claim and pharmacy refill were pending",
        this_week="this week medicine schedule and transport are the constraint",
        next_week="doctor follow-up appointment",
        open_loop="call pharmacy about refill",
        observation="expense pharmacy 63 USD",
        expected_terms=("insurance", "pharmacy", "medicine", "doctor"),
        current_terms=("medicine", "transport"),
        last_week_terms=("insurance", "refill"),
        next_week_terms=("doctor", "follow-up"),
    ),
    Archetype(
        id="household_move",
        timezone="America/Denver",
        fact_key="life_stage",
        fact_value="moving apartments",
        last_week="last week movers quote and utilities transfer were unresolved",
        this_week="this week packing and inspection checklist are active",
        next_week="new apartment inspection and keys pickup",
        open_loop="confirm movers quote",
        observation="expense boxes 38 USD",
        expected_terms=("movers", "utilities", "packing", "inspection", "keys"),
        current_terms=("packing", "checklist"),
        last_week_terms=("movers", "utilities"),
        next_week_terms=("inspection", "keys"),
    ),
    Archetype(
        id="personal_finance",
        timezone="Asia/Singapore",
        fact_key="life_stage",
        fact_value="budget reset",
        last_week="last week credit card balance and rent payment were stressful",
        this_week="this week spending freeze and meal prep are the plan",
        next_week="salary deposit and credit card autopay",
        open_loop="review credit card statement",
        observation="expense lunch 14 SGD",
        expected_terms=("credit", "rent", "spending", "salary"),
        current_terms=("spending", "meal"),
        last_week_terms=("credit", "rent"),
        next_week_terms=("salary", "autopay"),
    ),
)


def build_diverse_stress_cases(*, overload_history: bool = True) -> list[StressCase]:
    cases = [_case_from_arch(archetype) for archetype in ARCHETYPES]
    if overload_history:
        cases.extend(_overload_cases())
    return cases


def _case_from_arch(arch: Archetype) -> StressCase:
    return StressCase(
        id=arch.id,
        evidence=TemporalEvidence(
            user_id=f"eval-{arch.id}",
            now=EVAL_NOW,
            timezone=arch.timezone,
            name=arch.id.replace("_", " ").title(),
            facts={arch.fact_key: {"value": arch.fact_value}},
            chat_messages=[
                _item("chat", arch.last_week, "2026-04-16T09:00:00+00:00", role="user"),
                _item("chat", arch.this_week, "2026-04-22T10:00:00+00:00", role="user"),
            ],
            observations=[
                _item("observation:tracker", arch.observation, "2026-04-22T13:00:00+00:00"),
            ],
            open_loops=[
                _item("open_loop", arch.open_loop, "2026-04-22T11:00:00+00:00"),
            ],
            calendar=[
                _item("calendar", arch.next_week, "2026-04-28T07:00:00+00:00"),
            ],
        ),
        expected_terms=arch.expected_terms,
        expected_current_terms=arch.current_terms,
        expected_last_week_terms=arch.last_week_terms,
        expected_next_week_terms=arch.next_week_terms,
        stale_terms=arch.stale_terms,
    )


def _overload_cases() -> list[StressCase]:
    """Noisy histories check that caps preserve the important week model."""
    cases: list[StressCase] = []
    for base in ARCHETYPES[:8]:
        noise = [
            _item("chat", f"small unrelated note {idx} for {base.id}", f"2026-04-2{idx % 3}T0{idx % 9}:00:00+00:00", role="user")
            for idx in range(20)
        ]
        evidence = TemporalEvidence(
            user_id=f"eval-overload-{base.id}",
            now=EVAL_NOW,
            timezone=base.timezone,
            name=base.id.replace("_", " ").title(),
            facts={base.fact_key: {"value": base.fact_value}},
            chat_messages=[
                _item("chat", base.last_week, "2026-04-16T09:00:00+00:00", role="user"),
                *noise,
                _item("chat", base.this_week, "2026-04-22T10:00:00+00:00", role="user"),
            ],
            observations=[
                _item("observation:tracker", base.observation, "2026-04-22T13:00:00+00:00"),
            ],
            open_loops=[
                _item("open_loop", base.open_loop, "2026-04-22T11:00:00+00:00"),
            ],
            calendar=[
                _item("calendar", base.next_week, "2026-04-28T07:00:00+00:00"),
            ],
        )
        cases.append(
            StressCase(
                id=f"overload_{base.id}",
                evidence=evidence,
                expected_terms=base.expected_terms,
                expected_current_terms=base.current_terms,
                expected_last_week_terms=base.last_week_terms,
                expected_next_week_terms=base.next_week_terms,
                stale_terms=base.stale_terms,
            )
        )
    return cases


def dataset_summary(cases: list[StressCase]) -> dict[str, Any]:
    timezones = sorted({case.evidence.timezone for case in cases})
    return {
        "cases": len(cases),
        "timezones": timezones,
        "timezone_count": len(timezones),
        "with_observations": sum(1 for case in cases if case.evidence.observations),
        "with_open_loops": sum(1 for case in cases if case.evidence.open_loops),
        "with_calendar": sum(1 for case in cases if case.evidence.calendar),
        "overload_cases": sum(1 for case in cases if case.id.startswith("overload_")),
    }


def _item(kind: str, text: str, at: str, role: str | None = None) -> TemporalItem:
    return TemporalItem(kind=kind, text=text, at=datetime.fromisoformat(at), role=role)
