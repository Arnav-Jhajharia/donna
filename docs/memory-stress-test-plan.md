# Donna Memory Stress Test Plan

Status: **draft, 2026-04-25**. Scope: the full nine-backend memory stack — what gets written, what gets surfaced, how it cross-connects, how it behaves across time horizons.

## The question we're actually answering

Not *"do the backends store things"* — that's covered by unit tests. The real question:

**When Arnav asks anything, does Donna have a coherent, time-aware picture assembled from every relevant backend, and does she use it?**

That's situational awareness. It breaks down into four orthogonal axes:

1. **Coverage** — are writes landing in every backend they should?
2. **Retrieval** — when a query could benefit from a backend, does Donna reach it?
3. **Temporal correctness** — does "today" mean the user's today, does "an hour ago" return the right window, does "last week" respect Monday rollover in user TZ?
4. **Cross-connection** — can Donna answer a question that requires combining two or more backends?

Everything below is designed to stress one or more of those axes.

---

## Phase 0 — preconditions (must fix before honest testing)

Testing a broken system gives you known failure modes back. These gaps would pollute the run:

- **`smart_recall` doesn't fanout to observations or open_loops** (`backend/memory/retrieval/fanout.py:30-33` — only Supermemory + Graphiti lanes). Any multi-hop query involving countable state would silently miss. Fix: add `_search_observations` and `_search_open_loops` lanes, ~100 LOC.
- **Situation brief refresh is post-write only** (`backend/memory/tools/log_observation.py:91-104`). Chat-only users go stale for days. Fix: wire `run_forever` per `docs/memory-wireup-plan.md` Phase 2, ~60 LOC.
- **Brief rendering was dumping raw evidence** — fixed this session, but Arnav's polluted facts row should be confirmed clean before running.
- **TODAY block (next-24h calendar + today's observations + active open loops + active attentions) is not rendered into the prompt.** Without it, every "today" / "tomorrow" / "right now" question forces tool calls the model shouldn't need to make.

**Decision:** land these four fixes first. Without them, the stress test reveals known bugs and blocks measurement of the interesting failures (cross-connection, temporal boundary errors, derivation quality).

---

## Phase 1 — the nine-backend surface map

Every backend, every read interface, every write interface. Single source of truth.

| # | backend | write paths | read paths | used by |
|---|---|---|---|---|
| 1 | Graphiti (FalkorDB) | `ingest_to_graph` post-hook | `search_facts` in fanout | smart_recall auto |
| 2 | Supermemory — episodic | `record_episode` post-hook | `search_with_graph` in fanout | smart_recall auto |
| 3 | Supermemory — docs | (none in pipeline yet) | (none in pipeline yet) | dormant |
| 4 | Procedural rules | manual SQL | (none) | dead code |
| 5 | Observations (Postgres) | `log_observation` via `remember(observation)` | `list_observations`, `list_observations` in fanout *(after phase 0)* | `recall(observations)`, TODAY block |
| 6 | Open loops (Postgres) | `track_open_loop` / `close_open_loop` via `remember` | `list_open_loops`, `list_open_loops` in fanout *(after phase 0)* | `recall(open_loops)`, TODAY block |
| 7 | user_facts / living_profile (JSONB) | `update_user_fact` via pre-BRAIN detector + post-turn extractor; `temporal_brief.synthesize_and_store` | `get_user_facts`, `get_living_profile`, `load_and_render` | USER MODEL block, SITUATION BRIEF block |
| 8 | chat_messages (Postgres) | `save_chat_messages` post-hook | `_safe_recent_chat` | RECENT CHAT block |
| 9 | Calendar (Postgres, Google sync) | Google sync job | `list_calendar` | `check_calendar`, TODAY block |

Gaps in the table = gaps in the plan (Supermemory-docs and procedural-rules are dormant; stress test deprioritizes them).

---

## Phase 2 — seed corpus

A realistic synthetic user, 30 days of history across every backend. This is the input to every test. Build once, reuse everywhere.

**User profile:**
- `preferred_name: "Kai"`, `current_city: Singapore`, `home_city: Toronto`, `profession: founder`
- `current_timezone: Asia/Singapore`, with one 3-day trip to `America/New_York` in the middle
- `onboarding_goals: {tz_done: true}`

**Chat messages (~200 lines over 30 days):**
- 50% substantive turns, 50% chatter
- Mix of voice: frustrated, upbeat, planning, venting, quick yes/no
- Mentions 6-8 people (2 cofounders, 2 investors, 2 friends, 1 family), 3-4 companies, 2 cities
- Multiple proactive-style messages from Donna (ack + motion)

**Observations (~60 entries):**
- `expense`: 25 entries, varied merchants, avg $15, weekend spikes
- `meal`: 18 entries, 3 per day on random weekdays
- `mood`: 7 entries with score + note
- `sleep`: 6 entries with hours
- `habit`: 4 entries (workout, meditation)

**Open loops (~8 at various ages):**
- Fresh (0-2 days): "confirm dinner with maya"
- Medium (4-7 days): "respond to saurabh's term sheet"
- Stale (14+ days): "refactor ingest gate"
- One that gets resolved mid-corpus → `close_open_loop`

**Calendar (~25 events):**
- Past: 5 board syncs, 3 1:1s with cofounders, 2 investor meetings
- Upcoming 7 days: 4 meetings including a recurring weekly 1:1
- Upcoming 14-30 days: 3 events including a flight

**Graphiti entities + relations:**
- Ingested from chat via post-hook; expect ~15 entities, ~20 relations after 30 days of seeding
- Verify: Kai ↔ Maya (cofounder), Maya ↔ Stripe (works_at), Kai ↔ Toronto (home_city)

**Supermemory episodic:**
- One episode per multi-line chat exchange
- Thematic tags: "stress", "fundraising", "relationships", "product"

**Situation brief:**
- Generate three versions: fresh (< 1h old), 3-day stale, 14-day stale. Stress the freshness axis.

Script: `scripts/seed_stress_corpus.py` — idempotent, uses Postgres truncate + insert, fixture chat, fake Graphiti/Supermemory shim for offline runs.

---

## Phase 3 — the test matrix

Every row is one prompt + expected behavior + backends it should touch. We run the full BRAIN loop per row.

### 3.1 Single-hop — does each backend answer its own thing

| query | expected verb call | expected backend | pass criteria |
|---|---|---|---|
| *"who am i"* | (no tool — rendered in USER MODEL) | users.facts | reply mentions "kai", "founder", "singapore" |
| *"how much did i spend this week"* | `recall(observations, period=this_week)` | observations | reply cites numeric total |
| *"what's on tomorrow"* | `check_calendar` | calendar | reply lists tomorrow's events |
| *"what am i forgetting"* | `recall(open_loops)` | open_loops | reply lists at least 2 active loops |
| *"summarize my week"* | `recall(situation_brief)` | living_profile | reply cites brief content, not fabricated |
| *"what did i tell you about maya last week"* | `recall(auto)` | Supermemory | reply references maya-related episode |
| *"what do i know about stripe"* | `recall(auto)` | Graphiti | reply cites entity/relations |

### 3.2 Multi-hop — cross-backend stress

These are the tests that actually fail today without phase 0 fixes.

| query | backends required | pass criteria |
|---|---|---|
| *"what did i eat before my 2pm yesterday"* | calendar (find event) + observations (meal before event_time) | reply identifies the meal + time |
| *"how much have i spent at places maya recommended"* | Graphiti (maya ↔ place) + observations (expense at those places) | reply joins person to merchant |
| *"who was at my last board meeting"* | calendar (most recent "board") + Graphiti (attendees) | reply lists attendees |
| *"last time i was this stressed, what was happening"* | Supermemory (emotion search) + observations (context around date) | reply gives a historical comparison |
| *"what did i commit to in my last chat with saurabh"* | Graphiti (saurabh) + chat_messages (last with saurabh) + open_loops (any derived) | reply cites the commitment |
| *"what's my situation right now"* | USER MODEL + SITUATION BRIEF + TODAY block + open_loops | reply composes all four layers |

### 3.3 Temporal correctness — TZ and window math

Seed data includes a 3-day NY trip. Period queries must respect which TZ was active on which dates.

| query | window semantics | pass criteria |
|---|---|---|
| *"what did i do today"* | `today` in current TZ | no yesterday bleed-through |
| *"what happened an hour ago"* | last 60 min (Postgres UTC) | returns most recent chat + obs |
| *"last monday what was my mood"* | local `last_monday` → UTC bounds | hits correct date, respects NY→SG tz shift |
| *"compare this week to last week spending"* | two SUM queries, Mon 00:00 local boundaries | correct weekly bucketing |
| *"what did i do 3 days ago in new york"* | period bounded by `America/New_York`, not `Asia/Singapore` | TZ-aware period derivation |
| *"show me yesterday's logs"* | `yesterday` in current TZ | excludes midnight-overlap noise |

### 3.4 Derivation — did the system infer, not just store

Backends should extract structure that wasn't explicitly stated.

| query | what we're testing | pass criteria |
|---|---|---|
| *"what company does maya work at"* (after user chat mentioned "maya from stripe") | Graphiti inferred the relation | reply: stripe, not "i don't know" |
| *"what have i been thinking about lately"* | Supermemory thematic pattern | reply names 1-2 recurring themes |
| *"what's my routine"* | living_profile pattern detection | reply names 1-2 habits with weekly frequency |
| *"who do i talk to most"* | Graphiti centrality | reply names the most-connected entity |
| *"am i spending more than usual"* | observations delta against prior weeks | reply quantifies delta |

### 3.5 Correction + propagation

Writes must flow through all the right backends within-turn or same-turn-next-turn.

| test | flow | pass criteria |
|---|---|---|
| user corrects name mid-chat | pre-BRAIN detector → users.facts → USER MODEL next turn | name updated in the SAME turn's prompt |
| user corrects timezone | `remember(timezone)` → users.timezone + bitemporal facts + onboarding_goals | period_bounds in next observation query use new TZ |
| user resolves a loop | `remember(loop_closed)` → open_loops.status=resolved | disappears from `recall(open_loops)` and from brief's open_loops |
| third-party name mentioned | extract_user_facts hook should REJECT | user.facts.preferred_name unchanged (regression test for the Aayam fix) |
| user logs an expense | `remember(observation)` → observations + brief refresh | next turn's SITUATION BRIEF reflects it |

### 3.6 Failure injection — graceful degradation

Break each backend in turn, measure whether the BRAIN reply is useful or catastrophic.

| injected failure | expected degradation |
|---|---|
| Supermemory timeout (lane > 8s) | smart_recall returns Graphiti-only results |
| Graphiti unavailable | smart_recall returns Supermemory-only |
| Postgres slow (observations query > 2s) | list_observations returns degraded → model says "can't reach it" not "you spent $0" |
| living_profile empty | USER MODEL block skipped cleanly, no `None` leaks |
| Calendar sync broken | check_calendar returns no_hits, brief shows stale_or_uncertain flag |

### 3.7 Voice coherence — does retrieved data flow into the reply cleanly

Even with perfect data, the model can fumble synthesis. Sample assertions:

- No raw tool output echoed back ("- supermemory: ...")
- No "based on my memory" / "according to the data" filler
- Numeric answers include the number, not "some"
- When memory contradicts the prompt context, Donna picks one source cleanly (no "according to X but Y says")

---

## Phase 4 — instrumentation

Every turn run through the stress test writes a record to `scripts/_out/memory_stress_<run_id>.jsonl`:

```json
{
  "query_id": "multihop_expense_at_maya_places",
  "query": "how much have i spent at places maya recommended",
  "tools_called": ["recall", "check_calendar"],
  "backends_hit": ["supermemory", "graphiti", "observations"],
  "latency_ms": {"expansion": 120, "fanout": 480, "rerank": 18, "total_turn": 4200},
  "tokens": {"input": 5200, "output": 180, "total_cost_usd": 0.018},
  "reply_body": "…",
  "judge": {"passed": true, "reason": "cites maya + stripe + $210 correctly"},
  "trace_file": "…jsonl pointer…"
}
```

Judge is an LLM-based pass/fail — small Haiku call that reads the expected criteria + the reply and votes. Sampled-audit by hand after.

---

## Phase 5 — analysis

After running the matrix:

- **Coverage matrix** — which backends got hit for which query classes; highlight underused backends (are they dead weight or unused potential?)
- **Accuracy** per section — single-hop, multi-hop, temporal, derivation, correction, failure, voice
- **Latency/cost** distribution — p50/p95 per section; flag queries burning tokens for small answers
- **Cross-connection rate** — what fraction of multi-hop queries actually triggered >1 backend vs bluffed an answer from one
- **Root-cause catalog** — for every failure, a one-line diagnosis pointing at a file/function

---

## Phase 6 — expected known gaps (pre-test hypotheses)

If I had to bet on what'll break:

1. **smart_recall auto misses structured data** (phase 0 fix) — won't surface observations even for "how much did I spend" without explicit `purpose=observations`
2. **TZ boundary errors on "today" / "yesterday"** — Supermemory and observations both use UTC; user-local period math lives in `period_bounds`. Test if the pipeline actually uses it.
3. **Graphiti ingest gate is coarse** — fast_reject at <20 chars; fast_accept on multi-turn. Short high-signal turns like "sarah moved to paris" might get dropped.
4. **Situation brief is week-bucketed, not hour/day granular** — "what's happening an hour ago" won't surface there
5. **Cross-connection queries hit 2 tools serially, not 1 fanout** — expensive, slow, and the model often gives up after tool 1
6. **Living profile extraction is narrow** — only the 7-12 fact keys. "What's my routine" has no structured answer path.
7. **No episodic ↔ observation linkage** — Supermemory episode of "stressed about fundraising" doesn't link to the `mood=3` observation from same day

Each of these is a fixable thing once the test names it with data.

---

## Phase 7 — execution plan

Sequential, each stage gates the next.

1. **Phase 0 fixes** (~1 day) — observations lane in fanout, periodic brief refresh, TODAY block, polluted facts cleanup
2. **Seed corpus script** (~0.5 day) — idempotent generator with fake Graphiti/Supermemory clients for offline; real clients when integration test
3. **Test harness** (~0.5 day) — runs a matrix of prompts through `donna_turn`, captures traces, judge-scores
4. **Judge prompt** (~0.25 day) — Haiku-based pass/fail with explicit rubric
5. **First full run** — ~120 queries × 1 turn each, real backends, real model. ~$5-10 in API spend
6. **Analysis** (~0.5 day) — produce the five artifacts in Phase 5
7. **Fix round 1** — top 5 failures by severity × frequency
8. **Second run** — confirm regression test, measure delta

Total: ~1 week of focused work to produce the first real signal.

---

## Exit criteria

- 90%+ single-hop queries correct
- 70%+ multi-hop cross-connection queries correct
- 95%+ temporal-boundary queries correct
- Every failure has a root cause cited with file:line
- No silent degradation — every backend failure logs a structured event
- Cost per turn documented; credible path to the CLAUDE.md per-turn budget (<$0.01 on Haiku)

---

## Out of scope for this plan

- Attention subsystem (its own stress test lives under `docs/attention-observation-alignment-plan.md`)
- Dashboard rendering (separate QA)
- Voice quality beyond "did the reply use retrieved data cleanly" (smoke_eval owns that)
- Production load / concurrency (this is correctness + cross-connection, not perf)

---

## What this plan is NOT

- Not a unit test suite. Unit tests cover "backend stores/returns." This covers "Donna can assemble a real picture."
- Not an LLM benchmark. We're testing memory architecture, not model quality.
- Not a one-shot — it's reproducible, because the seed corpus is deterministic.
