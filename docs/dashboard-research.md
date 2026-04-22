# Dashboard Research — toward the perfect moment

Working notes. Not a spec. The goal is to figure out what Donna's dashboard should actually BE before we build more of it.

## North star

> Show the right thing at the right time in the dashboard. The correct thing. The thesis for that moment in time.

That is a claim about **intent**, not layout. It means every plan should answer one question first: *what is the single most useful thing for this user to see right now, and what shape does that take?*

Everything downstream — block vocabulary, generator, memory wiring — is in service of that claim.

---

## What makes a good moment-interface

### 1. Thesis-first, not feed-first

A social feed ranks items. A dashboard ranks everything equal (or by recency). Donna's surface has to do something different: it commits to a **thesis** — a single sentence about this moment — and then renders blocks that serve that thesis.

Compare:
- Feed-first: "here are 14 things sorted by relevance"
- Thesis-first: "today is about calling dad before it gets weirder. here are three blocks that serve that."

This is more like a newspaper's A1 than a feed. A1 has a lead story and supporting coverage. The thesis is the lead.

### 2. Glanceable in 6 seconds, felt for the rest of the day

Prior art worth studying:
- **Apple Watch Smart Stack** — time-aware, one card at a time, swipe-revealed
- **Android At a Glance (Pixel)** — two-line density, never loud
- **Arc Max / Rewind** — ambient "what happened while you were gone"
- **Readwise Daily Review** — curation over comprehension
- **Granola Daily Summary** — single-page thesis, no feed
- **Day One "On This Day"** — memory as emotional artifact
- **Stoic / How We Feel** — mood-aware, register-aware
- **Things 3 Today view** — a ruthless single list, not a dashboard

What these share: **they all commit**. They pick one angle for the moment and stake the UI on it. They don't hedge by showing everything.

### 3. Emotional register is a design primitive

The current block vocabulary (hero, whisper, todo, tracker, nudge, footer) is informational. It can carry content but not **register**. Donna's voice has registers — blunt, witnessing, celebratory, confronting, permissive — and the dashboard should too, or it will feel flatter than her chat.

Proposed register palette:

| register | feels like | when Donna uses it |
|---|---|---|
| witness | "i saw you" | quiet observation, no demand |
| confrontation | "stop lying to yourself" | when user is drifting from stated values |
| celebration | "you did the thing" | quiet acknowledgment of something landed |
| permission | "rest is work" | when user is burning |
| reflection | "what was today?" | evening, journal-adjacent |
| invitation | "we could try this" | low-pressure new option |
| reminder | "this is still open" | open loops, threads |

Each deserves a block type tuned to it. A whisper can carry any register, but a block that commits to one register lets the generator say one specific emotional thing.

### 4. Density and register budgets

A plan with two heroes, three confrontations and a celebration is emotionally incoherent. The plan schema should enforce budgets:

- **density**: total "visual weight" per plan capped
- **register**: max one confrontation AND one celebration per plan (emotional coherence)
- **hero rule**: one hero, top
- **rust rule**: one featured accent per screen (already enforced: R-C1)

Budgets are the design-system's defense against generator drift.

### 5. Time-of-day is a real schema dimension

The same user state produces different plans at 7am vs 10pm. Morning is forward-leaning. Midday is check-in. Evening is reflective. Late night is permissive. The generator should gate block choices on a **moment tag**.

Moment tags (draft):
- `dawn` (pre-6am — rare, assume sleep-broken)
- `morning` (6-10am — forward-leaning, thesis about the day ahead)
- `midday` (10am-2pm — check-in, short, functional)
- `afternoon` (2-5pm — productivity inflection, open loops surface)
- `evening` (5-9pm — reflection starts, calendar shape matters)
- `night` (9pm-12am — reflective, permission-giving)
- `late` (past midnight — minimal, "go to bed")

### 6. Novelty cadence

If the user opens the dashboard twice in an hour, should it feel different? My bet: **no, until the next anchor**. Anchors are the time-tags above. Between anchors, the plan can update *content* (a tracker number, an open loop closed) but not *thesis*. This keeps the surface trustworthy and cheap.

### 7. Not every moment deserves a full dashboard

Sometimes the right answer is: one sentence. One block. "Go to bed, Aarav." A plan with one block is a valid plan. The schema and renderer should welcome sparse plans, not fight them.

### 8. Dashboard as donna's mirror, not just her screen

Donna sees the user; the dashboard is how she shows what she saw. That reframes it. The hero isn't "good morning" — it's "here's what i noticed about you." The blocks aren't features — they're evidence.

---

## Inputs the generator needs

From existing memory layers:
- **Living Profile** — who they are, rhythms, season-of-life
- **Open loops** — unfinished threads
- **Trackers** — streaks and metrics
- **Attention flags** — things Donna marked for surfacing
- **Insight cards** — things Donna explicitly wrote for the dashboard
- **Calendar** — shape of today
- **Recent observations** — emotional/energy signal from chat
- **Recent messages** — short-term context
- **Time of day** — moment tag

Missing infra:
- A **read-side snapshot** that collects these into one queryable object
- An **event bus** so Donna's writes invalidate the current plan
- A **plan store** so renders are consistent across opens

---

## Generator architecture

```
trigger (anchor or event)
   └─ gather(MomentContext) from 9 backends
      └─ compose(thesis): one sentence
         └─ compose(plan): blocks that serve the thesis
            └─ validate(schema + budgets)
               └─ store + emit
```

The thesis step is load-bearing. It's the difference between a feed and a point of view.

**Model split:**
- Anchor plans → Sonnet, quality matters, cached
- Event deltas → Haiku, cheap, invalidates specific blocks
- Fixtures in dev → rule-based composer (what we're building today)

---

## Rendering consistency

Plan as contract:
- LLM picks blocks + writes copy + picks sequence
- LLM never touches layout, tokens, motion
- Design system enforces visual coherence
- Validator rejects malformed plans before render

This is the same discipline as Notion blocks, tldraw shapes, or Figma auto-layout — **expressive within constraint**.

---

## Open questions

1. **One surface or many?** (morning / evening / check-in) — affects generator routing
2. **Does Donna reference the dashboard back in chat?** — "i see you opened it at 7 this morning" — makes dashboard state bidirectional
3. **Tap-to-expand or static?** — every block could open into a conversation with Donna
4. **Persistence of state across opens?** — is the current plan a snapshot or always-live?
5. **Who acts when the user taps a CTA?** — Donna or the user? affects agency model

---

## What we're building in this sprint

1. Expanded block vocabulary with emotional register
2. Density + register budgets in the validator
3. Six moment plans across time-of-day and user state
4. A moments gallery page for side-by-side comparison
5. A rule-based thesis-first generator that proves the architecture
