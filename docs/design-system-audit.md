# Design System Audit — gospel vs dashboard

Working notes. Written 2026-04-25. Source of truth: `donna-design-system/DESIGN_SYSTEM.md`.

The gospel is the spec. The dashboard is the implementation. They have drifted. This document catalogs every divergence so the team can close the gap.

---

## The two token files

| | Gospel | Dashboard |
|---|---|---|
| path | `donna-design-system/tokens.css` | `dashboard/web/app/globals.css` |
| role | "the only source of truth" | de facto runtime |
| structure | role names (`--color-paper`, `--color-ink`, `--color-rust`, `--color-muted`) + type roles (`--type-h1-size`, utility classes `.type-h1`, `.type-body`) | scale-only names (`--paper-100`, `--ink-900`) + semantic aliases (`--fg-primary`, `--bg-canvas`). No type roles. No utility classes. |

Both files agree on the palette hex values. They disagree on how to reference them and on whether type is tokenized.

---

## Divergence list

### D1 · No type role tokens in dashboard

The gospel tokens the whole type scale (h1 through input, 12 roles) plus utility classes (`.type-h1 .. .type-input`). The dashboard has **none** of these. Every block inlines raw pixel font sizes.

Evidence:
- `components/blocks/ThesisBlock.tsx:25` → `fontSize: 22` (should be `.type-h3`)
- `components/blocks/WitnessBlock.tsx:36` → `fontSize: 15` (should be `.type-h4`)
- `components/blocks/TrackerGridBlock.tsx:72` → `fontSize: 28` (arbitrary — no role in the scale)
- `components/blocks/NudgeGridBlock.tsx:69` → `fontSize: 17` (arbitrary — no role in the scale)
- `components/blocks/OpenLoopsBlock.tsx:30` → `fontSize: 15` (should be `.type-h4`)

Impact: violates rule §0.2 ("Never introduce a raw px font-size").

### D2 · Italic misuse

Gospel §3 permits italic in exactly three places: one word inside H1/H2, proper nouns inline, or verbatim quoted memory.

Violations:
- `ThesisBlock.tsx:27` wraps the **entire thesis sentence** in italic. Not an accent word, not a quote. Bug per §3 row 4 ("Italic page titles — whole heading").
- `OpenLoopsBlock.tsx:45` uses italic on the **whole commitment line**. Not a quoted memory; this is a commitment summary. Bug per §9 item 3.

Fix: drop italic from whole-sentence bodies. Reserve italic for the three allowed shapes.

### D3 · Token name drift

Dashboard introduces a parallel vocabulary that shadows the gospel:

| Gospel | Dashboard |
|---|---|
| `--color-paper` | `--bg-canvas` (aliases `--paper-100`) |
| `--color-surface` | `--bg-surface` (aliases `--paper-300`) |
| `--color-ink` | `--fg-primary` (aliases `--ink-900`) |
| `--color-muted` | `--fg-muted` (aliases `--ink-500`) |
| `--color-rust` | `--fg-accent` (aliases `--rust-700`) |
| `--border-hairline: var(--ink-300)` | `--border-hairline: var(--alpha-ink-08)` |

The last row is a real semantic divergence, not a renaming: the gospel's hairline is a solid `#B5A89F`. The dashboard's hairline is an 8%-ink overlay. They look similar on paper bg, they diverge on any tinted card.

Fix: pick one. Suggest keeping the gospel's solid `--ink-300` hairline (crisper, no alpha stacking issues).

### D4 · Radius drift

| token | gospel | dashboard |
|---|---|---|
| `--radius-sm` | `4px` | `6px` |
| `--radius-md` | `8px` | `10px` |
| `--radius-lg` | `12px` | `16px` |

Dashboard is softer by 2–4px across the board. Impact: buttons and inputs read slightly rounder than spec.

Fix: conform to gospel. Or: update gospel, but then flag `components.md` update simultaneously.

### D5 · New color introduced

Dashboard adds `--paper-600: #B8A89B` (globals.css:10). Not in `donna-design-system/tokens.css`.

Violation of §9 rule 1 ("A new hex color anywhere in code"). Usage in the repo is small — worth deleting.

### D6 · Alpha overlays used decoratively

Dashboard uses `rgba(251,247,245,0.14)` and `rgba(251,247,245,0.75)` directly inline in `NudgeGridBlock.tsx:57, 78`. The gospel allows exactly one rgba: the rust-link underline (`--border-rust-link`).

Fix: promote these to tokens if they're structural, delete if decorative. Two new `--on-rust-*` aliases would cover them.

### D7 · Blocks don't use design-system components

The components in `donna-design-system/components/index.tsx` (Heading, Accent, Label, Card, Button, Chip, Link, Divider, Wordmark) are **never imported** in the dashboard. Every block re-implements its own heading, label, and card treatment with raw `<div>` + inline styles.

Impact: every future change to the design language has to be applied in N places. Spatial memory is enforced by discipline, not by type system.

Fix: import from `@donna/design-system` (or co-locate the components in `dashboard/web/components/ds/`) and rewrite each block to compose them. This is the big one.

### D8 · Rust budget not runtime-enforced in dashboard

`ScreenRoot` in `donna-design-system/components/index.tsx` has a rust-budget context that warns in dev when more than one accent appears. The dashboard's `DashboardRenderer` has no such guard — it only validates the *plan* (`validatePlan` in `lib/plan.ts`), which catches `nudge-grid` featured counts but not rust usage inside ad-hoc blocks.

Fix: wrap `DashboardRenderer` in `ScreenRoot`. All rust-carrying blocks (featured nudge, listening chip, accent word) spend from the same runtime budget. Dev console warns on overspend.

### D9 · Typography weights

Gospel §2 bans serif weight 700 ("If you need more weight than 500, the layout is wrong"). Dashboard uses `fontWeight: 500` on serif in several places, which is fine. No instances of 700 serif spotted — this is the one area with no drift.

### D10 · No bridge from attention CardTypes

The attention system produces 6 `CardType`s (see `donna/attention/vocabulary.py:70`): EventStream, Tally, Brief, PrepDoc, OpenLoop, Ping. The dashboard has 15 block types. **No adapter connects them.** Today the dashboard consumes static fixtures; the generator is rule-based over a hand-shaped `MomentContext`.

Impact: every attention Donna creates is invisible to the dashboard. The promise "every affordance is a Lego block" is aspirational, not real.

Fix: `dashboard/web/lib/attention-adapter.ts` — pure functions from each attention card's output to a `Block`. Added in this PR.

---

## Priority (for future migration)

1. **D10** (attention adapter) — biggest user-visible gap. Unblocks dynamic plans.
2. **D7** (use design-system components) — biggest maintenance gap. Kills most other drift as a side effect.
3. **D1** (type roles) — ships naturally with D7 if components carry their own type.
4. **D2** (italic misuse) — cheap fix, big readability win.
5. **D8** (rust budget runtime guard) — cheap, catches future drift.
6. **D3, D4, D5, D6** — bundle as a "tokens reconciliation" PR once D7 is in.

---

*Not a spec. Snapshot of the gap on 2026-04-25.*
