# Attention Runtime — From Spec to Contract

**Status:** planning
**Owner:** TBD
**Estimate:** ~11 focused days, four phases

## Thesis

The attention system today is a beautifully designed declarative spec store. The spec is rich — sources, extractor, cadence, surface_policy, dedup, nudge_policy. What's missing is the runtime that turns those declarations into behavior.

`card=tally` (the "track this for me" pattern) is the most affected: tally attentions sit dormant, meal observations don't carry calorie counts, no rollup ever computes, no schedule ever fires, the dashboard fabricates numbers. `card=ping` works partially via the existing schedule_worker. `card=event_stream` and `card=brief` work partially via the proactive dispatcher. The system as a whole is half-built.

The product goal: **make every field in the attention spec a load-bearing contract.** When a user says "track my calories," every component the spec describes (observation tagging, schema enforcement, rollup computation, surface policy, escalations, nudges) actually runs. The dashboard, the brain, and the proactive system can all read trustworthy rolled-up state.

CLAUDE.md says reliability is the brand. Today's calorie tracker is in the betrayal state — looks alive, does nothing. Fixing this is structural, not cosmetic.

## What "fully built" looks like end-to-end

For a calorie tracker created by the user:

1. User sends *"had chicken rice for lunch"* via WhatsApp.
2. The **meal observation hook** writes a `type=meal` observation. It also looks up live tally attentions whose `sources.tag` matches and ensures the `schema_hint` fields are present. Calories aren't in the message, so the hook calls a small estimator (lookup table + Haiku fallback) → `calories: 550, confidence: medium`. The observation now carries `fields.calories=550, tags=["meal_calories", attention_id]`.
3. The **rollup worker** runs every 10 minutes. For each live tally attention, it queries today's observations matching `sources.tag` in the user-local day window, runs the rollup (deterministic sum, here), and writes `attention.current_state = {day, value, count, target, computed_at, evidence_observation_ids}`. The attention's `last_update_at` is bumped.
4. The **schedule spawner** materializes `cadence.params.cron = "0 21 * * *"` into a `DonnaSchedule` row scheduled for 9pm in the user's timezone. At fire time, the row's payload routes to the surface executor.
5. The **surface executor** reads the attention's `current_state` and evaluates `surface_policy`. Default is silent → no WhatsApp burst, just a state refresh. But it also walks `escalations[]`. If `daily_total > 2300` is true, it fires a WhatsApp burst with an escalation message. `last_surfaced_at` is updated.
6. The **nudge watcher** runs hourly. For each live tally with `nudge_policy.if_silent_for_seconds`, it checks if any observation was tagged in that window. If silent, it fires the `nudge_text` via WhatsApp ("log your meals for today?"). Then it backs off (24h → 48h → 72h → stop, re-engaging when the user logs anything).
7. The **dashboard composer** reads `attention.current_state` directly when building the brief. The `c-tracker` block now gets `value: "1240"` and `progress: 0.62` from real data, not LLM inference.
8. The **brain TODAY block** also gets the rollup. When the user asks "how am I doing on calories?", the brain has the answer inline — no recall needed.
9. A `recall(purpose="tally")` retrieval lane returns rolled-up state for any tally attention by subject.

That's the contract.

## What's missing today (gap analysis)

Field by field across `AttentionSpec`:

| Field | Should drive | Built? |
|---|---|---|
| `sources.type = "internal_observations"` | Observations queried by tag for rollup | Partial — fanout queries observations but never filters by attention tag |
| `sources.params.tag` | Observations tagged with this string at write time | **No.** Meal extractor doesn't tag |
| `sources.params.schema_hint` | Required fields enforced on observations created against this spec | **No.** Schema hint is metadata only |
| `extractor.prompt` | Rolled-up state computed from observations | **No.** Prompt sits in JSONB, no consumer |
| `cadence.cron` (with `card=tally`) | DonnaSchedule rows materialized at user-local cron times | **No.** schedule_worker handles `card=ping` only |
| `cadence.cron` (with `card=ping`) | DonnaSchedule rows | **Yes.** Existing path works |
| `cadence.type = "on_event"` | Triggered by external event subscription | Partial for event_stream watches via dispatcher |
| `surface_policy.default` ("silent") | Don't push WhatsApp on fire, just update state | **No.** No surface executor for tally |
| `surface_policy.escalations[]` | Conditional WhatsApp push when condition matches `current_state` | **No.** No conditional engine |
| `surface_policy.nudge_policy` | Idle-watcher fires text when silent for N seconds | **No.** Not implemented |
| `surface_policy.urgent_if` / `resolve_if` | Auto-transition state | **No.** Not implemented |
| `relevance_threshold` | Quality gate before push | **No.** Not implemented |
| `dedup` | Don't fire same payload twice in window | **No.** Not implemented |
| `expires_at` | Auto-resolve attention after deadline | **No.** Not implemented |
| `promotion_criteria` | Auto-promote shadow → live | Not relevant for tally |
| `current_state` (read surface) | Composer + brain read latest rollup | **No.** Doesn't exist on the row |

The spec is loadbearing in design and ornamental in code.

## Architecture: four runtime layers

Designed so each layer is independently buildable and testable.

### Layer 1 — Observation tagging + schema enforcement

**Job:** when an observation is written, look up live attentions whose `sources.tag` could match. For each match, ensure the observation carries the `schema_hint` fields. Either auto-fill (Haiku estimate, regex parse, lookup table) or queue a follow-up question.

**Where it lives:** PostToolUse hook on `log_observation`, called after the observation is constructed but before commit. Cooperates with the existing extract_user_facts hook.

**For calories specifically:**
- Lookup table for common Indian/Singaporean food items (poha = 250, banana = 100, chicken rice = 550, biryani = 700, etc.). Cheap, deterministic, ~50 entries.
- Haiku fallback for unknown items: *"Estimate kcal for: <item description>. Reply with `<int>` or `unknown`."* Cached per item string.
- Confidence flag on the result: `high` (lookup table hit), `medium` (Haiku confident), `low` (Haiku said unknown / fallback to a guess).
- When confidence is `low`, optionally enqueue a Donna follow-up: *"rough kcal on that?"* — but only once per day, never spammy.

**Output:** observation row gets `fields.calories: int`, `fields.calorie_confidence: str`, `tags: ["meal_calories", attention_id]`.

**Generalization:** the schema_hint shape is a small grammar. `field: type` pairs the enforcer can interpret. For tally attentions the common shapes are `count: int`, `amount: float`, `value: int`. The estimator strategy is per-tag (the meal hook handles `meal_calories`; sleep handles `sleep_hours`; spend handles `amount_local_currency`).

### Layer 2 — Rollup worker

**Job:** for each live attention with non-trivial state, materialize today's rolled-up state.

**Where it lives:** new `backend/memory/jobs/attention_rollup_worker.py`. Polls every 10 minutes (configurable). Designed to coexist with the existing `synthesis_worker` and `schedule_worker`.

**Per attention pass:**
1. Compute the user-local day window for the user's timezone.
2. Query observations matching `attention.spec.sources.params.tag` in that window.
3. Run the rollup logic:
   - **Deterministic path:** sum / count / latest / boolean — covers most tally specs. For calorie intake: `value = sum(fields.calories)`.
   - **Haiku path:** when the rollup logic isn't expressible as a simple aggregate (e.g., "summarize this week's design sector news"), invoke Haiku with `extractor.prompt` and the observation list. Cached on (attention_id, day, observation_ids_hash).
4. Write `attention.current_state = {day, value, count, target, computed_at, evidence_observation_ids, source: "deterministic"|"haiku"}`.
5. Bump `attention.last_update_at`.

**Idempotency:** keyed on `(attention_id, user_local_day)`. Safe to re-run.

**Dirty flag optimization:** observation writes flip an attention's `rollup_dirty: bool`. Worker skips clean attentions. Recomputation only when something changed. Drops 90%+ of work for inactive trackers.

**Cost:** with deterministic rollup, near-zero. With Haiku rollup, ~$0.001 per attention per tick. With dirty-flag optimization, ~5–20 Haiku calls per user per day worst case = ~$0.02/user/day.

### Layer 3 — Surface executor + cron spawner

**Job:** translate `cadence` + `surface_policy` into actual side-effects.

**Where it lives:** extend the existing `schedule_worker` for `card=tally` cron support. Add a `surface_executor` module that interprets `surface_policy`. Add a `nudge_watcher` worker for the idle-detection path.

**On schedule fire (cron-based):**
1. Read attention's `current_state`.
2. Evaluate `surface_policy`:
   - If `default = silent` and no `escalations[]` match → no-op (just refresh state).
   - If any `escalations[].condition` matches → fire WhatsApp burst with the escalation's `text` (or a Haiku-composed line if `text` is templated).
3. Update `last_surfaced_at`. Apply `dedup` policy (don't repeat same content within window).

**On rollup update (event-driven):**
1. Same surface_policy evaluation. Catches "user just logged a meal that pushed total over 2300" → escalation fires immediately, not at the next cron.

**Nudge watcher (separate small worker):** every hour, for each live attention with `nudge_policy`:
1. Check if any observation was tagged with this attention in the last `if_silent_for_seconds`.
2. If silent and we haven't nudged today → fire `nudge_text`.
3. Back off: 24h → 48h → 72h → stop. Re-engage on next observation.

**Condition language:** start with simple expressions evaluated against `current_state` fields. Examples:
- `daily_total > 2300`
- `value < target * 0.5`
- `count == 0 AND now > today_at("18:00")`

A small safe-eval module — a whitelist of operators + a known set of context vars. No full DSL.

### Layer 4 — Read surfaces

**Job:** make `current_state` available wherever the brain or dashboard might consume it.

**Three readers:**

1. **Dashboard composer** — `_format_live_attention` includes the rollup string, e.g. *"calorie intake today: 1240 of 2000 (3 entries, last meal 1:14pm)"*. The c-tracker block now gets `value` from `current_state.value`. Composer prompt is updated to use ONLY the rolled-up number; never infer from observation strings.
2. **Brain TODAY block** (`donna_runtime/context_builder.py`) — when listing active attentions, attach the rollup. So when the user texts "how am I doing today?" the brain has the data without a recall.
3. **`recall(purpose="tally")` lane** — new structured lane in the retrieval pipeline. Filters by attention type, returns `RetrievalResult` with `current_state` attached. Useful when the brain wants tally state across multiple subjects ("show me everything I track").

## Phased delivery

### Phase 1 — Wedge: tally rollups end-to-end (3 days)

**Day 1: Observation tagging + estimator**
- Add `attention_id` and `tags` to observation schema.
- New `backend/memory/observations/schema_enforcer.py` — looks up live attentions, runs per-tag estimators, fills `schema_hint` fields.
- New `backend/memory/observations/calorie_estimator.py` — lookup table + Haiku fallback.
- Hook into `log_observation` PostToolUse.
- Tests: meal logged with various item strings → calorie field populated.

**Day 2: Rollup worker**
- New `backend/memory/jobs/attention_rollup_worker.py` (poll cadence 10 min).
- New `backend/memory/attention/rollup_engine.py` — deterministic + Haiku paths.
- DB migration: add `current_state JSONB`, `last_update_at`, `rollup_dirty bool` to attentions.
- Observation write flips `rollup_dirty=true` on matching attentions.
- Tests: synthetic meals → rollup runs → `current_state` matches expected sum.

**Day 3: Composer reads rollup**
- Update `_format_live_attention` in `compose.py` to include `current_state` summary line.
- Update composer system prompt: "Tally attention rollups in the brief are the ONLY source of truth for tracker values. Do not infer numbers from meal names. If `current_state` is null, render `value: "—"` and `detail: "not yet logged today"`."
- Verify Arnav's calorie tracker on the dashboard shows real numbers within 30 min of any meal logged via WhatsApp.

**Phase 1 ship criteria:** the calorie tracker is end-to-end real for a single user. No fabricated numbers on the dashboard. The "how am I doing on calories" question can be answered.

### Phase 2 — Schedule + surface (3 days)

**Day 4: Cron spawner extension for tally**
- Extend `schedule_worker` to walk `card=tally` attentions and materialize their `cadence.cron` into `DonnaSchedule` rows.
- User-local timezone resolution (existing helper).
- Tests: tally with `cron="0 21 * * *"` → DonnaSchedule rows created at 9pm local.

**Day 5: Surface executor**
- New `backend/memory/attention/surface_executor.py`.
- Condition language module — `condition_eval.py` with whitelisted ops.
- On schedule fire OR on rollup update → evaluate `surface_policy`, fire WhatsApp burst when escalations match.
- Default-silent path verified.

**Day 6: Nudge watcher**
- New `backend/memory/jobs/attention_nudge_worker.py` (poll cadence 1h).
- Idle detection per attention.
- WhatsApp burst with `nudge_text`.
- Backoff schedule.

**Phase 2 ship criteria:** the calorie tracker fires its 9pm cron, default-silent. Contrived overshoot (>2300) produces an escalation burst. Going silent for 24h produces a nudge.

### Phase 3 — Extend to other card types (3 days)

**Day 7: event_stream rollups**
- Watches (ADBE, Poke launch) — rollup is "latest signal + delta from last fire."
- Surface_policy escalations: "delta > 5%" → WhatsApp burst.

**Day 8: prep_doc rollups**
- Pre-meeting prep — rollup is "checklist completion state."
- Auto-resolves on `expires_at` hitting.

**Day 9: brief rollups**
- Briefs — rollup is "next_fire datetime + last_fire summary snapshot."
- Surface to composer for `c-brief variant=index` blocks.

### Phase 4 — Observability + reliability (2 days)

**Day 10: Operator dashboard**
- Internal page (lives at `/admin/attention-runtime`) showing every active attention per user with: last rollup, last fire, last nudge, drift detection, error rate.

**Day 11: Alerts**
- Stale rollup alert: any live attention without a rollup in the last 30 min.
- Missed fire alert: any DonnaSchedule row past `fire_at + 60s` with status `pending`.
- Executor error alert: any surface_executor exception.
- Tally drift detector: a tracker that's been silent for 7 days with the user still active in chat.

## Reliability principles (from CLAUDE.md)

CLAUDE.md says reliability is the brand. Concrete commitments:
- **A live tally attention with no rollup in the last 30 min is an alert.** Worker stuck = page someone.
- **A `DonnaSchedule` row that should have fired but didn't is an alert.** Already a stated principle; this work adds tally to its scope.
- **An observation that should have been tagged but wasn't is logged for inspection.** Catches silent extractor failures.
- **The user always sees the truth on the dashboard.** If `current_state` is null, the c-tracker shows "not yet logged today" — never an LLM-inferred number.

## Open design questions

1. **Where does `current_state` live?** Options: (a) JSONB column on the existing `attentions` table, (b) separate `attention_rollups` table keyed on `(attention_id, day)` with history. (b) is cleaner for multi-day analysis but adds a join. **Default: (a) for v1, migrate to (b) when we need history queries.**

2. **Haiku-driven rollup vs deterministic.** Calorie sum is deterministic. "Did the user run today" is deterministic boolean. "Summarize the design sector this week" is Haiku. **Start deterministic; only invoke Haiku when the rollup logic isn't expressible as a simple aggregate.**

3. **Schema hint enforcement strictness.** When a meal is logged without calories, options: (a) auto-estimate via Haiku, (b) ask the user, (c) write null. **Default: (a) with a confidence flag; Donna asks ("rough kcal?") only when confidence is `low` AND we haven't asked today.**

4. **Backfill of existing observations.** Arnav has had a calorie tracker since 2026-04-26 with no calorie data. Backfill (Haiku-estimate every existing meal) or start fresh? **Default: start fresh; offer manual backfill via an internal CLI.**

5. **Surface policy condition DSL richness.** `daily_total > 2300` is easy. `daily_total > 2300 AND time_of_day < 6pm` (catch binge before dinner) is harder. **Default: start narrow with field comparisons; add temporal predicates only when a real attention spec needs them.**

6. **Nudge fatigue.** Backoff schedule (24h → 48h → 72h → stop), re-engage on next observation. Already specified above; flagging it as a design call to confirm.

7. **Cross-attention conflicts.** Two tally attentions both tagged `meal_calories` — which one rolls up which observations? **Default: each observation rolls up to ALL matching live attentions. Specs should not duplicate; if they do, both rollups are valid.**

8. **Privacy of rollup data.** Rollups (today's calories, today's spend) are sensitive. The /admin operator dashboard should redact values by default; show on click-through with audit log.

## Surface area & code touchpoints

**New files:**
- `backend/memory/jobs/attention_rollup_worker.py`
- `backend/memory/jobs/attention_nudge_worker.py`
- `backend/memory/attention/rollup_engine.py`
- `backend/memory/attention/surface_executor.py`
- `backend/memory/attention/condition_eval.py`
- `backend/memory/observations/schema_enforcer.py`
- `backend/memory/observations/calorie_estimator.py`
- `backend/memory/observations/sleep_estimator.py` (Phase 3)
- `backend/memory/observations/spend_estimator.py` (Phase 3)
- `dashboard/web/app/admin/attention-runtime/page.tsx` (Phase 4)

**Extended:**
- `backend/memory/jobs/schedule_worker.py` — handle tally crons
- `backend/dashboard/compose.py` — read `current_state`, update prompt
- `donna_runtime/context_builder.py` — TODAY block reads `current_state`
- `db/models.py` — add `current_state JSONB`, `last_update_at`, `rollup_dirty bool` to attentions; add `attention_id`, `tags` to observations
- `donna/attention/store.py` — `current_state` accessor + `mark_dirty` helper
- `backend/memory/retrieval/fanout.py` — new tally lane (Phase 4)

**Migrations:**
- `alembic/versions/<timestamp>_add_attention_current_state.py` (Phase 1)
- `alembic/versions/<timestamp>_add_observation_tags.py` (Phase 1)

## What this isn't

- **Not a UI for managing attentions.** Out of scope; covered by existing /admin pages. This work is the runtime behind the existing UI.
- **Not bidirectional sync with external systems** (Apple Health, Google Fit, Strava). Rollup worker reads internal observations only. External-source attentions are a sibling project.
- **Not a re-architecture of the proactive dispatcher.** The dispatcher reads attentions today and will continue to. This work makes the data it reads richer.
- **Not an LLM-driven goal achievement system.** `extractor.prompt` is bounded — sum, count, classify, summarize. Open-ended planning ("how do I lose weight?") stays the brain's job.
- **Not a replacement for the brain's recall.** Rollup state coexists with semantic recall; they answer different questions.

## Success criteria

**After Phase 1 ships:**
- Arnav's calorie tracker shows a real number on the dashboard within 30 min of any meal logged.
- Every digit traces to specific observations (audit-able).
- The composer never fabricates numbers — replaced by "not yet logged today" when null.

**After Phase 2 ships:**
- 9pm cron fires reliably for the calorie tracker. Default-silent path: dashboard updates, no WhatsApp burst.
- Escalation path works: a contrived test with calories > 2300 produces the right alert burst.
- Nudge fires after 24h of silence; backoff schedule observed.

**After Phase 3 ships:**
- Every card type (`tally`, `event_stream`, `prep_doc`, `brief`, `ping`, `open_loop`) has a working rollup. Dashboard surfaces real state for all of them.

**After Phase 4 ships:**
- Operator dashboard shows every active attention with rollup freshness, fire history, nudge history.
- Failed runs alert.
- Drift detector flags trackers gone silent.

## After this lands: what unlocks

- **The dashboard composer can stop fabricating numbers.** Truth replaces vibes.
- **The brain's TODAY block becomes anchored.** "How am I doing today?" answered from real state.
- **The proactive dispatcher gets sharper signals.** Tier 2 judge can read rollup deltas, not just metadata.
- **The user feels Donna actually paying attention.** That's the product promise.
