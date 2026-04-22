# Day-in-the-Life Eval Suite

End-to-end behavioral evals derived from a single user day (Arnav, 2026-04-19 WhatsApp session). Each scenario in `scenarios.jsonl` is a user-turn (or proactive trigger) plus the behavior Donna must exhibit.

## Why this exists

Unit tests cover tool mechanics. Attention evals cover proposer/hit calibration. This suite covers the **end-to-end BRAIN loop** on realistic multi-turn days: voice, tool selection, agency level, open-loop capture, profile inference.

## What we are grading

Per scenario, four axes:

1. **Tool selection** — did the loop call the right tools (and only those)?
2. **Agency level** — L0 (ask) vs L1 (act + inform) vs L2 (act silently) matches `expected_agency`.
3. **Voice** — lowercase, no em dash, no filler, confident. Hard fail on forbidden tokens.
4. **Render target** — WhatsApp burst vs dashboard card vs internal state only.

Plus two cross-cutting axes evaluated at the end of the day:

5. **Open-loop capture** — every should-capture fact ended up in observations/open-loops/living-profile.
6. **Profile inference** — Living Profile at EOD contains `expected_profile_deltas` without the user ever being asked onboarding questions.

## Scoring

- **pass@3 > 90%** on capability scenarios (`kind: capability`)
- **pass^3 = 100%** on regression scenarios (`kind: regression`) — any flake fails the suite
- **cost/turn < $0.01** median on reactive turns (Haiku + caching)

## Scenario schema

```
{
  "id": str,                          # stable id
  "t": str,                           # ISO-ish local time, e.g. "17:40"
  "kind": "capability" | "regression" | "proactive",
  "mode": "reactive" | "proactive",
  "user_msg": str | null,             # null for proactive triggers
  "context": { ... },                 # minimal state needed (day_so_far, profile facts, calendar)
  "expected_tools": [str],            # subset of tool names that MUST be called
  "forbidden_tools": [str],           # tools that MUST NOT be called
  "expected_agency": "L0" | "L1" | "L2",
  "expected_render": ["whatsapp"] | ["dashboard"] | ["whatsapp","dashboard"] | ["internal"],
  "expected_behaviors": [str],        # natural-language assertions (LLM-judged)
  "forbidden_behaviors": [str],       # hard fails (LLM-judged)
  "expected_profile_deltas": [str],   # facts that should land in living profile by EOD
  "expected_open_loops": [str],       # open-loops that should exist after this turn
  "notes": str
}
```

## Running

```
DONNA_RUN_LLM_EVAL=1 python -m donna.evals.day_scenarios.run
```

(Runner is TODO — this spec + gold file is step 1.)

## Coverage map

| Theme                       | Scenario ids |
| --------------------------- | ------------ |
| Cold start + value pitch    | `d01_hey`, `d02_what_can_you_do` |
| Ambiguity handling          | `d04_meeting_raj_ambiguous_time`, `d11_lunch_plus_reach_office` |
| Passive logging             | `d05_lunch_subway`, `d20_paan_icecream`, `d23_medicine` |
| Profile inference (dark)    | `d08_washing_machine`, `d14_raj_insight_daughter` |
| Proactive surfacing         | `d13_post_raj_checkin`, `d19_priya_wedding_surface`, `d10_morning_brief` |
| Compound / conditional      | `d07_groceries_conditional`, `d11_lunch_plus_reach_office` |
| Link ingestion              | `d12_forwarded_article` |
| Open-loop long horizon      | `d19_priya_wedding_surface`, `d24_sumit_chimney` |
| Draft assistance            | `d06_draft_leave_email` |
| Archetype + dashboard       | `d10_morning_brief`, `d17_restaurant_pick` |

## Pass criteria for the whole day

At EOD replay of the 24-scenario tape:

- Living Profile contains: `occupation=working_professional`, `primary_work_channel=email`, `location=Mumbai`, `social=true`, `household_members≥1 (Sumit)`, `close_contacts=[Raj, Priya, Dave, Sumit]`, `raj.has_kids=true`, `office_arrival_window=~09:00-11:00`.
- Open-loops list contains at least: `plan_family_outing_with_raj`, `priya_wedding_gift_plan`, `chimney_repair_followup`, `buy_groceries_today`.
- Zero onboarding questions asked. All profile facts inferred from conversation.
- Zero em dashes, zero "I understand", zero "Great question" across the whole tape.
