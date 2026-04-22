# Dashboard Sprint — what shipped

A 45-min sprint toward the "perfect dashboard for the perfect moment." Not production. A proof of the architecture.

## What's live

Dev server: **localhost:3001**
- `/` — single dashboard (morning fixture), with nav to the other two views
- `/moments` — six hand-authored plans side-by-side, each with its thesis labelled
- `/generator` — the same six scenarios rendered by a **live rule-based generator** from MomentContext

## Reframe

The dashboard is not a feed. It is a **generated interface** that commits to a **thesis** — one sentence about the moment — and chooses blocks to serve it. Every plan now carries a mandatory `thesis: string` field. The validator enforces it.

## What was built

### 1. Research doc
`docs/dashboard-research.md` — prior art (Smart Stack, Readwise, Granola, Things, Day One, Stoic), emotional register as a design primitive, density/register budgets, moment tags, generator architecture, open questions.

### 2. Schema expanded (`lib/plan.ts`)
Added eight new block types, each tuned to a specific emotional register:

| block | register | purpose |
|---|---|---|
| `thesis` | — | the one sentence Donna commits to |
| `witness` | witness | "i saw you" — quiet observation |
| `confrontation` | confrontation | blunt callout, oxblood accent |
| `celebration` | celebration | "you did the thing" — moss accent |
| `reflection` | reflection | evening prompts, journal-adjacent |
| `open-loops` | reminder | threads Donna is tracking, with age |
| `weather-of-you` | witness | mood + energy + evidence |
| `calendar-shape` | — | the day at a glance, kind-tinted |
| `permission` | permission | "rest is work" — dashed border |

Added to `DashboardPlan`: `thesis`, `moment` (time-tag). Added validation rules:
- **P-TH1** — max one thesis block
- **P-TH2** — plan requires a non-empty thesis string
- **P-R1** — register budget (max 1 confrontation AND 1 celebration)
- **P-R2** — warn if confrontation + celebration coexist (emotionally incoherent)
- **P-D1** — density budget of 12 with per-block weights

### 3. New icons
Added: `moon`, `sun`, `heart`, `leaf`, `eye`, `hourglass`.

### 4. Nine new block components
All in `components/blocks/`. Framer Motion stagger preserved. Tokens-first styling — nothing hardcoded outside globals.

### 5. Six hand-authored moment plans (`lib/plans/`)
- `morning-crisp` — forward-leaning, calendar-shape + nudges, featured CTA
- `morning-after-bad-day` — weather + permission + witness, no trackers
- `midday-check` — trackers + one open loop, short
- `evening-reflection` — thesis as question, reflection prompts, one confrontation
- `celebration-moment` — lead with the landing, quiet forward-look
- `low-energy` — four blocks total, thesis + permission + witness + footer

Each demonstrates a different register composition. None overlap.

### 6. Thesis-first generator (`lib/generator.ts`)
- `MomentContext` — the read-side snapshot shape (the future seam where all 9 memory backends feed in)
- `momentTagFor(date)` — IST-anchored time tagging
- `composeThesis(ctx)` — rule-based priority: safety → celebration → recovery → evening-reflection → aging-loop → default
- `composeBlocks(ctx, thesis)` — register-aware, budget-aware composition
- `generatePlan(ctx)` — top-level; logs density + issues in dev

Architecture ready to swap: replace `composeThesis` and `composeBlocks` with LLM calls. Everything else stays. `MomentContext` becomes the input to the generator's system prompt.

### 7. Six scenarios (`lib/scenarios.ts`)
Fixtures that simulate MomentContext outputs from memory — the `/generator` page renders each live.

### 8. Two new pages
- `/moments` — hand-authored gallery with density counters + thesis chips
- `/generator` — live-composed gallery proving the rule-based path works

## Observations from seeing them side-by-side

- **Thesis chips make the dashboard legible even at thumbnail size.** You can scan six dashboards and read the point of view without rendering them.
- **Register budget works.** The plans feel emotionally distinct. The recovery plan and the celebration plan cannot be confused with each other.
- **Density budget catches bloat early.** The morning-crisp plan is right at the ceiling (hero 3 + thesis 1 + witness 1 + calendar 2 + nudge 3 = 10). Adding a tracker would push it to 12. That's the point.
- **Restraint is visible.** The low-energy plan (4 blocks) is as valid as the morning-crisp plan (6 blocks). The schema welcomes sparse plans.
- **Generator thesis rules already produce good judgment.** Aging loops outrank generic status lines at midday. Spiral state routes to restraint. Recovery mornings suppress trackers.

## What's NOT done

- **No LLM in the loop yet.** Generator is rule-based. The LLM swap is the next step.
- **No real memory wiring.** `MomentContext` is typed but not populated by any real backend.
- **No write path.** `add_insight_card` / `flag_attention` / `update_living_profile` still don't land anywhere the generator reads.
- **No event bus / anchor scheduler.** The generator is called on render, not on time anchor or event.
- **No store.** Plans are composed every render. A real system caches per-anchor.
- **Not mobile-visited.** Designed for 440px column, but no device testing this pass.
- **Attention subsystem still unwired.** Separate from this sprint but the adjacent gap.

## Suggested next moves

1. Define the `MomentContext` collector — one function per memory backend that extracts the one thing the generator needs
2. Prompt-draft for the LLM composer, with the rule-based generator as ground truth for evals
3. Anchor scheduler (morning / midday / evening / night) that regenerates the plan
4. Plan store (Postgres row per user per anchor, versioned)
5. Golden moment evals — "monday 7am after bad sunday" → expected thesis shape
6. Device pass + motion tuning on real hardware
