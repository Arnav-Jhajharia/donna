# Design system session · 2026-04-25

Autonomous run. ~30 minutes. What was built, why, and what's next.

## Tldr

- audited the drift between `donna-design-system/` (gospel) and `dashboard/web/` (runtime). 10 divergences catalogued.
- built the missing **attention → dashboard block adapter**. the dashboard can now render any of Donna's six attention `CardType`s without bespoke UI.
- shipped a **static design-system showcase** (`donna-design-system/showcase/index.html`). visual reference card. no build step.
- ported the gospel components to the dashboard (`dashboard/web/components/ds/index.tsx`) so blocks can migrate off raw-style `<div>`.
- locked the **block contracts** into `components.md` — one block per attention CardType, plus Offer.
- every build (Next.js + TS) passes with no new errors.

## Files touched

### new

- `docs/design-system-audit.md` — catalogue of gospel ↔ dashboard divergences (D1–D10), prioritized
- `docs/design-system-session-2026-04-25.md` — this file
- `donna-design-system/showcase/index.html` — static visual reference, all tokens + blocks on one page
- `donna-design-system/showcase/README.md` — how to view, what's on it, keeping it in sync
- `dashboard/web/lib/attention-adapter.ts` — pure functions from attention CardType payloads → Block
- `dashboard/web/lib/plans/from-attention.ts` — demonstration fixture: every block composed by the adapter
- `dashboard/web/components/ds/index.tsx` — `<ScreenRoot> <Heading> <Accent> <Label> <Card> <Button> <Chip> <Link> <Divider>` ported from gospel

### edited (additive, no breaking changes)

- `donna-design-system/components.md` — added 7 block contracts (EventStream, Tally, Brief, PrepDoc, OpenLoop, Ping, Offer) before the "Components NOT allowed" section
- `dashboard/web/app/globals.css` — added gospel token aliases and the 12 type-role utility classes (`.type-h1` … `.type-input`). blocks can now swap raw `fontSize: 22` for `className="type-h3"`
- `dashboard/web/app/moments/page.tsx` — added `from-attention` plan to the gallery

## The core insight

The dashboard already has 15 rich emotional-register block types (hero, witness, confrontation, celebration, reflection, etc.) but **the attention subsystem had no way to reach them.** Every block today is driven by static fixtures or hand-shaped `MomentContext`.

The adapter closes this:

```
Attention (event_stream)  →  OpenLoopsBlock
Attention (tally)         →  TrackerGridBlock
Attention (brief)         →  WitnessBlock
Attention (prep_doc)      →  ReflectionBlock
Attention (open_loop)     →  OpenLoopsBlock (single-item form)
Attention (ping)          →  WhisperBlock
```

Every attention Donna writes, regardless of domain, lands as one of these shapes. Hydration tracker = tally. Fundraising digest = brief. Maya's flight = ping or open_loop. No domain-specific UI. That is the Lego promise.

## What's still to do (next session)

Prioritized from the audit:

1. **migrate existing blocks to `components/ds/`** (audit D7). the biggest maintenance win — kills D1 (raw px) and D3 (token drift) as side effects. estimated: 2–3 hours per block × 15 blocks, but many are small.
2. **wrap `DashboardRenderer` in `<ScreenRoot>`** (audit D8). one-line change that wires the rust budget runtime guard across every plan.
3. **unify `--radius-*` tokens** (audit D4). dashboard is currently 2–4px softer than gospel. pick one.
4. **remove `--paper-600`** (audit D5). not in gospel. grep usage first.
5. **fix the italic-on-whole-sentence bugs** (audit D2): `ThesisBlock` and `OpenLoopsBlock`. editorial judgment: is a full-sentence thesis considered "her memory verbatim" under §3? probably not. flag to team.

## To view

- showcase: open `donna-design-system/showcase/index.html` directly in a browser
- dashboard (dev server already running): http://localhost:3003/moments — scroll to "midday · from attention" (last in the gallery)

## Verification

- `dashboard/web` full `next build` + TypeScript passes before and after every commit of this session.
- showcase HTML contains 198 `var(--...)` token references and zero raw hex values used for styling (the 10 hex strings in the file are all inside display swatches or the forbidden-list text — content, not CSS).

— session end.
