# Dashboard spec

The north star (from `dashboard/CLAUDE.md`):

> Show the right thing at the right time in the dashboard. The correct thing,
> thesis for that moment in time.

The dashboard is mobile-first. It is one screen, scrollable, made of blocks
that the brain picks per moment per user. The brain composes a manifest;
the dashboard renders it. Style is determined by block type, not by the
brain. The brain's only job is taste and timing.

This doc is the contract between the brain and the renderer.

## 1 · The contract

A `DashboardManifest` (alias: `DashboardPlan`) is a single JSON document.
The brain writes it. The dashboard reads it. There is no other channel.

```ts
interface DashboardPlan {
  id: string;                          // "plan:<user>:<date>:<moment>"
  generatedAt: string;                 // ISO timestamp
  user: { name: string; initial: string };
  thesis: string;                      // the one sentence for this moment
  moment: 'dawn' | 'morning' | 'midday' | 'afternoon' | 'evening' | 'night' | 'late';
  blocks: Block[];                     // ordered, hero (if any) first
}
```

The full `Block` discriminated union lives in
[`dashboard/web/lib/plan.ts`](../dashboard/web/lib/plan.ts). 19 block types:

**Status (read-only)**
- `hero` — date + greeting + city/weather + illustration
- `thesis` — the one sentence
- `whisper` — Donna's voice as a soft note
- `witness` — "I saw you" observation
- `weather-of-you` — mood + energy snapshot
- `calendar-shape` — today at a glance
- `tracker-grid` — 1–3 metric cards
- `relationship` — people on her mind
- `news-brief` — proactive content cards
- `open-loops` — threads still open
- `reflection` — evening journal prompts
- `footer` — Donna's listening footer

**Action / hybrid (write)**
- `todo-list` — three I picked for you, with checkboxes
- `reminders` — time-anchored alerts for today
- `nudge-grid` — 4-up of small action cards
- `tracker-starter` — Donna offers to start a new tracker
- `permission` — connect a service
- `confrontation` — "stop lying to yourself" with an ask
- `celebration` — "you did the thing"

Each interactive item carries an optional `action: ActionVerb` — see §3.

## 2 · Composition rules (validation enforced)

These are checked by `validatePlan()`; warnings ship to console, errors
should never happen in production manifests.

| Rule | Constraint |
|---|---|
| `R-C1` | One rust per screen — at most one `featured` nudge across the whole plan |
| `P-H1` | At most one `hero`, must be the first block |
| `P-TH1` | At most one `thesis` block |
| `P-R1` | At most one `confrontation` AND one `celebration` per plan |
| `P-R2` | Confrontation + celebration in the same plan is incoherent (warning) |
| `P-D1` | Total density weight ≤ 12 — if higher the screen feels heavy |
| `P-T1` | `tracker-grid` items must be 1–3 |
| `P-TH2` | Plan must have a non-empty `thesis` string |

Density weights live in `plan.ts` (`DENSITY_WEIGHTS`). The brain should
target ~8–10 for a balanced day, climb to 12 for a "lots happening" day,
fall to 4–6 for "quiet, just a touch."

## 3 · ActionVerb (bidirectional interactivity)

Every interactive element on the dashboard carries an `ActionVerb`. The
flow on tap:

1. Optimistic UI update (strike-through, check, etc.)
2. POST `/api/dashboard/action` with `{ verb, user_id }`
3. Backend deterministically executes the state mutation
4. Hook fires (`PostDashboardAction`) — notifies brain via a queue
5. Two parallel things happen:
   - **Template ack** sent to WhatsApp instantly (no LLM, see action route)
   - **Brain follow-up** (sometimes) — composes a richer reply if warranted
6. Manifest re-composes; dashboard re-fetches on next poll

The full verb union lives in `plan.ts`. Examples:

```ts
{ v: 'start_tracker',     name: 'water' }
{ v: 'log_value',         tracker: 'calories', value: 320, unit: 'kcal' }
{ v: 'complete_pick',     pickId: 't1' }
{ v: 'snooze_reminder',   reminderId: 'r2', until: '6 pm today' }
{ v: 'connect_integration', provider: 'gmail' }
{ v: 'accept_draft',      draftId: 'peonies-order' }
{ v: 'reply_chip',        intent: 'tell luca I will be late' }
```

For phase 1 the action route logs and returns a templated WA ack only.
The verb mapping to actual backend tools lands in phase 2.

## 4 · When the manifest re-composes

**Hard triggers (deterministic, hook-driven)** — re-compose always:

1. **Day boundary** at 00:00 user TZ
2. **Proactive ping shipped** (`PostToolUse(send_burst, is_proactive=true)`)
3. **Integration state changed** (connector hooks)
4. **Open-loop transitions** (created / closed)
5. **High-signal observation logged** (gated by hook rules — e.g. expense
   over threshold, mood mark, etc.)

**Soft trigger (brain-callable tool)**:

- `update_dashboard()` — the brain calls this when, in a reactive turn,
  it judges that *what just happened* changes what the dashboard should
  show. The drunk → water example: the night turn logs the observation
  and calls `update_dashboard`; the day-boundary hook would have caught
  it anyway, but `update_dashboard` lets the brain force a fresh manifest
  immediately.

Composition is a pure function: `compose_manifest(user_id) → DashboardPlan`.
Phase 2 implementation should run a single Sonnet 4.6 call reading:

- profile + situation brief
- last 24h observations
- active open loops + open-loop transitions
- active watches + last deltas
- proactive judged pings since last compose
- integration states
- current local time / weather / city

Output: the manifest. ~1k tokens out, prompt-cached.

## 5 · Voice rules for dashboard copy

The voice is Donna. Her rules from `CLAUDE.md` apply, plus dashboard-specific:

- **Section titles**: sentence case, max 6 words, no period, serif.
- **CTAs**: imperative, lowercase, ≤ 3 words. "Log one." "Yes, order." "Remind me at six."
- **Source attributions**: "from messages", "from mail", "from calendar". Lowercase.
- **Numbers**: tabular numerals, always carry a unit. "₹ 8,200" not "8200".
- **Italics**: only for the wordmark, named pulls ("Aarav"), the permission block title, and the rationale in `tracker-starter`. Never elsewhere.
- **Em dashes**: never.
- **Whisper kicker**: "a note from me" (lowercase, uppercase tracking, rust accent).
- **One rust per screen**: only one `featured` nudge gets the rust fill.
- **Rationale** (witness, tracker-starter): quote the user's actual signal in italics. "she said it. don't paraphrase it."

## 6 · Phase split

**Phase 1 — interface exists, all interactions appear to work** ✓ (this PR)
- 19 block types, all rendered
- Mobile-first layout
- 7 fixture manifests covering different days/states
- Click handlers POST to backend stub, return success + fake-WA ack
- Manifest polling every 20s; manual fixture-switcher UI
- Drunk-water example renderable from a fixture
- Bidirectional action plumbing with stub backend

**Phase 2 — real internals** (separate PR)
- `compose_manifest(user_id)` real Sonnet call
- Day-boundary cron
- Hooks (PostToolUse send_burst, integration state, etc.)
- `update_dashboard` brain tool
- Real action verbs mutating state + triggering brain follow-ups
- SSE push instead of polling

## 7 · Files

| Concern | File |
|---|---|
| Schema (the contract) | `dashboard/web/lib/plan.ts` |
| Validation rules | `validatePlan()` in same file |
| Action context + toast plumbing | `dashboard/web/lib/action-context.tsx` |
| Manifest source (phase 1: fixture rotation) | `dashboard/web/lib/manifest-source.ts` |
| Block components | `dashboard/web/components/blocks/*.tsx` |
| Dashboard renderer (block switcher) | `dashboard/web/components/DashboardRenderer.tsx` |
| Manifest GET endpoint | `dashboard/web/app/api/dashboard/[user_id]/manifest/route.ts` |
| Action POST endpoint | `dashboard/web/app/api/dashboard/action/route.ts` |
| Page (fetch + poll + provide context) | `dashboard/web/app/page.tsx` |
| Toasts | `dashboard/web/components/Toasts.tsx` |
| Fixtures | `dashboard/web/lib/plans/*.ts` |

## 8 · The drunk → water worked example

A canonical situation that exercises the whole loop. See
`dashboard/web/lib/plans/drunk-water.ts`.

```
Night Tuesday 23:30
  user: bro had way too much tonight. losing it
  reactive turn:
    - log_observation(kind=mood, content="overdrunk", severity=high)
    - send_burst("get water + electrolytes. take a panadol now not in the morning.")
    - update_dashboard()    ← brain forces tomorrow's dashboard refresh

Wednesday 00:00 (day-boundary hook fires anyway as fallback)
  compose_manifest(user_id):
    inputs:
      - 24h obs includes mood=overdrunk
      - open_loop "feel better today"
      - sleep tracker shows 5h
    output sections:
      - hero: "Take it easy, Aarav."
      - witness: "last night was heavy. you texted me at 23:42."
      - tracker-starter: "start tracking water?" (action: start_tracker)
      - reminders: 3 time-anchored items (water, electrolytes, nap)
      - nudge-grid: 4 easy wins (log glass, skip gym, push pitch, tell Luca)
      - relationship: Luca card (action: open_relationship)
      - permission: "rest is work today."
      - footer
```

Three subsystems collaborating: **observation** logs the state,
**tracker** is offered, **attention** surfaces the easy wins. The brain
doesn't write any of this imperatively — it composes a manifest that
*describes* the day, and the layout engine renders it.
