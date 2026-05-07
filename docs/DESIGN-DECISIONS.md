# Donna v1 — Design Decisions & Context Handoff

**Purpose:** Compressed record of every architectural decision made in the design conversation that produced `PRD-donna-v1.md`. Read this first if you're a fresh Claude session continuing work on Donna.

**Status:** Living doc. Update as decisions evolve.

**Companion docs:**
- `PRD-donna-v1.md` — locked world engine spec
- `CLAUDE.md` (root) — voice, principles, non-negotiables

---

## 0. Five-minute orientation

Donna is a WhatsApp-native presence with persistent memory. She/her. Voice is in CLAUDE.md (lowercase, blunt, no em dashes, no semicolons).

**Codebase:** `donna-prod` (TypeScript, fresh rewrite). The Python repo at `Arnav-Jhajharia/donna` is the prior version — port concepts, not files. Active branch in this work: `claude/proactive-world-engine-PyUhz` on the python repo.

**Stack (locked):** Anthropic SDK direct, Sonnet 4.6 + Haiku 4.5, Postgres + pgvector, Supermemory (one external memory store), Composio (OAuth gateway for integrations), Twilio (WhatsApp + future voice), LangSmith (observability), Next.js (dashboard).

**The bet:** Tools serve perception + reasoning + action for the proactive brain. Reactive turns use the same tools. Proactive quality is upper-bounded by tool surface. The whole product follows from that.

---

## 1. Locked architecture

### 1.1 Five layers

```
SENSES        → MEMORY     → TOOLS      → BRAIN       → SURFACES
data sources    Postgres +   ~120 tools   Sonnet 4.6   WhatsApp
+ pollers       Supermemory  ~15 always   ReAct loop   Dashboard
+ webhooks                   loaded       reactive +   (Voice v2)
                             rest         proactive
                             deferred
```

### 1.2 Memory — two stores only

- **Supermemory** (per-user namespace): all fuzzy text — chat messages, observations, voice transcripts, photo captions, doc chunks, news items, RSS items. Single `kind` field tags each entry.
- **Postgres**: structured rows — users, expenses, sleep_log, mood_log, people, loops, scheduled_jobs, integrations, routes, raw_items, proactive_events, etc.

`recall(query)` fans out across both. ~10 lines of code.

### 1.3 Brain — one ReAct loop

Sonnet 4.6 via Anthropic SDK. Tool palette varies by mode (`reactive` / `proactive`) but is fundamentally the same set. No second mode beyond these two. No tier system.

Haiku 4.5 used inside narrow lanes only: proactive judge, post-turn fact extractor, image captioning, awareness scoring. Never as the primary brain.

### 1.4 Proactive engine

```
event → pre-score (deterministic) → Haiku judge → BRAIN(proactive) (if needed) → send_burst or stay silent
```

Rate limits: 3/day, 30min global cooldown, 30min per-topic cooldown, quiet hours (00-07 local default), 5min active-chat suppression.

### 1.5 Tools

~120 tools in catalog. ~15 always-loaded. Rest discoverable via `tool_search`. Same pattern as Claude Code's deferred-tools.

Coordination through three mechanisms only:
1. **Workflow tools** (frozen sequences) — most coordination is hidden inside specific tools
2. **Return envelope hints** (`followups`) — tool suggests next steps, BRAIN chooses
3. **Side effects** (`ctx.capture`, `ctx.observe`) — tools update user-model state without BRAIN reasoning

No execution agent. No mega-tool with `service` param. No DSL.

### 1.6 World engine (PRD-donna-v1.md owns this)

5 layers:
- **A** World substrate (universal pollers): GDELT, HN, NewsAPI, Fed, etc.
- **B** User watches (per-user, per-thing): stocks, packages, flights, YouTube channels, RSS, GitHub releases, sports, weather, NWS alerts, URL change
- **C** Integration sync (Composio fallback): Gmail, Calendar
- **D** Webhooks (push): Composio, TrackingMore, Twilio inbound, OAuth callback
- **E** Reactive-only (called per BRAIN turn): Wolfram, Exa, Foursquare, Nutritionix, Veryfi, Open Library, Finnhub, Translate

MCP vs direct API decision rule: MCP when a high-quality server exists; direct when wrapping value is in our code (Donna-specific magic); Composio for OAuth.

---

## 2. Explicitly rejected (do not re-propose)

These came up during design and were eliminated. Don't bring them back without strong evidence.

### 2.1 Tier system / mirror mode / counterfactual brain
Existed on `phase-1-usable` branch (Tier 2 Haiku judge + Tier 3 fat-context counterfactual running in mirror). Cut for v1. The judge stays (cheap filter); Tier 3 dies. Mode is now binary (`reactive` / `proactive`), not three palettes.

### 2.2 The "attention" abstraction as a top-level concept
Earlier design treated attentions as first-class objects with `attention.create(...)` constructors. Rejected. **Tools are verbs that DO things, not constructors for objects.** A reminder is `remind(when, text)`. A price alert is `set_price_alert(symbol, op, value)`. The persistent row is a side effect, not a managed entity BRAIN reasons about.

### 2.3 Generic primitive composition for everything
Considered reducing the catalog to a few generic verbs (`watch`, `log`, `note`, `schedule_check`) and letting BRAIN compose. Rejected. **Specific prebuilt tools beat generic composition** for anything that happens often. Generic verbs exist as fallbacks (~3-5 of them); the bulk is specific tools that just work.

Reference: Anthropic's "Building Effective Agents" — workflows where you can predict the steps, autonomy where you can't. Most life-tasks (weekly review, prep_for_meeting, recovery_check_today) have predictable shapes. Freeze them.

### 2.4 Multiple memory backends fanned out per recall
Prior design had Graphiti (FalkorDB) + Supermemory (episodic) + Supermemory (docs) + Postgres (facts) + bitemporal facts table + observations + open loops as separate stores. Five backends per recall. Rejected. **One external store (Supermemory) + Postgres for structured rows.**

### 2.5 LangGraph / LangChain / second framework
Anthropic SDK direct. Per CLAUDE.md.

### 2.6 An execution agent / orchestrator agent
Considered a separate "interaction agent" or "execution agent" to manage integrations + multi-step flows. Rejected. The BRAIN is the orchestrator. New tools + state, not new agents.

### 2.7 Mega-tool with `service` parameter
"One tool with `service: 'tracking' | 'flights' | 'weather'`" considered. Rejected. Each verb is its own tool with a clear schema and when-NOT-to-use.

### 2.8 17track for package tracking
Doesn't have a public API. Use **TrackingMore** instead (1,575 carriers, $9 for 200/mo).

### 2.9 ProPublica Congress API / GovTrack API
Both shut down. Use congress.gov direct + Open States MCP for civic data.

### 2.10 Pocket
Mozilla killed it July 2025. Use Readwise.

### 2.11 Twitter/X integration
Cost + noise. Skip.

### 2.12 Plaid in v1
Compliance overhead too high for MVP. Defer to v2. (Tink/TrueLayer/Nordigen in EU — same story.)

### 2.13 Slack/Discord/Teams
Work-narrow, fragments attention. Skip for v1.

### 2.14 Letterboxd/Trakt/Goodreads
Consumer-niche. Defer.

### 2.15 Google Maps API (post-2026 pricing)
Got expensive ($100/mo Starter). Use Mapbox or Geoapify when needed. Apple MapKit JS free.

---

## 3. Open questions (carry forward)

1. **Composio cost vs direct OAuth.** v1 uses Composio. Revisit at scale.
2. **MCP server quality vetting checklist** — auth, error shape, rate-limit, last commit. Define it before adopting community MCPs.
3. **changedetection.io: self-hosted or cloud.** v1 cloud ($8.99/mo). Revisit if URL-watch volume grows.
4. **Pre-scorer thresholds.** Empirical tuning needed. Start at score ≥ 0.3 (Layer A) and ≥ 0.5 (derivative). Ship with telemetry.
5. **Dedup window.** 7 days standard; longer for stable identifiers (tracking numbers until terminal state).
6. **Layer A fanout pattern.** NULL global rows in raw_items, per-user proactive_events only (recommended).
7. **Haiku judge bypass for high-confidence specific watches.** A package marked "delivered" probably doesn't need Haiku — known-shape event. Allow watch kinds to skip judge.
8. **Voice/SMS in v1?** Currently deferred to v2. Twilio Conversations is the substrate when ready.
9. **Embedding provider for Postgres `chat_messages.embedding`.** Voyage 3 primary, OpenAI text-embedding-3-small fallback.
10. **Auto-exclusion list for Gmail smart-index.** Initial defaults: labels (Banking/Finance/Medical/Legal/Confidential), sender heuristics, OTP/password-reset subject regex. Lock dashboard editor for refinement.
11. **Routes: where standard outputs go.** Capabilities like `daily_journal`, `weekly_review`, `expense_log` route to integrations or `donna_native` (Postgres). Set at first-use or integration connect.

---

## 4. Principles (locked, in priority order)

1. One agent loop. Sonnet via Anthropic SDK.
2. Specific prebuilt tools beat generic primitives for anything that happens often.
3. Tools are verbs, not constructors. No `create_X()` style.
4. Many tools is fine. Bloated context is not. Always-loaded ~15; rest deferred.
5. Memory = Supermemory + Postgres. Two stores. One `recall()`.
6. Workers are dumb. BRAIN is smart. Dispatcher decides when BRAIN wakes.
7. Tools serve perception + reasoning + action — not just action. The proactive brain's quality is the upper bound.
8. Privacy by default. Tiered consent (mode 1/2/3). Default = smart-index with auto-exclusions.
9. Workflows where you can predict the steps. Autonomy where you can't.
10. Reliability gates everything. A reminder that doesn't fire is a betrayal.

Reference for #2 + #9: [Anthropic — Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)

---

## 5. The full tool catalog (locked structure)

```
ALWAYS LOADED (15)
  send, ask, ack
  recall, remember, note, get_user_state
  search_web, web_search
  schedule_check, generic_watch
  remind, remind_recurring
  tool_search, cancel

DEFERRED — Personal logs (10)
  log_expense, log_calories, log_workout, log_sleep, log_mood,
  log_energy, log_water, log_substance, log_weight, log_med

DEFERRED — Captures (5)
  capture_link, capture_quote, capture_idea, capture_recipe, capture_book

DEFERRED — People (10)
  person_note, person_update, person_recall, person_list,
  person_last_touch, person_note_meeting,
  draft_message_to, schedule_with, last_convo_with, prep_for_meeting

DEFERRED — Loops (4)
  loop_open, loop_close, loop_list, loop_aging

DEFERRED — Prefs / Goals (5)
  pref_set, pref_get, goal_set, goal_update, goal_list

DEFERRED — Reflection (8)
  reflect, summarize_day, summarize_week, weekly_review,
  month_in_review, get_pattern, get_aggregate, relationship_check_in

DEFERRED — Health workflows (4)
  recovery_check_today, training_load, correlate_sleep_mood,
  nutrition_breakdown

DEFERRED — Finance workflows (3)
  spend_check, recurring_charges_review, budget_status

DEFERRED — Writing (4)
  draft_email_in_voice, draft_message_in_voice,
  edit_for_brevity, summarize_thread

DEFERRED — Discovery (4)
  find_restaurant_for, find_book_like, find_movie_for, find_recipe_for

DEFERRED — Magic verbs / specific watches (16)
  track_package, track_flight, set_price_alert, poll_score, follow_topic,
  watch_repo_release, watch_artist_release, watch_substack,
  watch_youtube_channel, watch_price_drop, watch_concert,
  watch_cheap_flight,
  find_places, compute_math, parse_receipt, transcribe_video, watch_url

DEFERRED — Single-call utilities (8)
  stock_price, crypto_price, news_search, weather_at,
  top_hn, score_of, translate, research_topic

DEFERRED — Integration management (9)
  integration.connect/status/set_mode/add_exclusion/start_sync/disconnect
  route.set/get/list

DEFERRED — Integration use (12)
  gmail.search/draft/send
  gcal.list/create/update
  notion.append/search
  spotify.recent
  readwise.recent_highlights
  health.metric (Terra)
  strava.recent
```

---

## 6. v1 ship list (subset of catalog)

~35 tools, 18 data sources, 2 OAuth integrations.

**Tools shipped at v1:**
- All 15 always-loaded
- All 10 personal logs
- 5 reflection (`reflect`, `summarize_day`, `weekly_review`, `get_pattern`, `relationship_check_in`)
- 5 magic (`track_package`, `set_price_alert`, `compute_math`, `find_places`, `parse_receipt`)
- All 5 captures
- 5 people (`person_note`, `person_recall`, `person_last_touch`, `prep_for_meeting`, `draft_message_to`)
- All 4 loops
- 4 integration management (`connect/status/set_mode/disconnect`)
- 6 integration use (gmail.search/draft/send, gcal.list/create/update)

**World sources at v1:** see PRD section 14.

**Day-1 reliability gates:** see PRD section 15.

---

## 7. Tool contract

```ts
// Every tool exports
{
  name: string,
  description: string,        // one-line + USE WHEN + DO NOT USE FOR
  schema: Zod schema,
  handler: (args, ctx) => Promise<ToolResult>,
  loaded: 'always' | 'deferred',
  tags: string[]              // for tool_search indexing
}

// Every handler returns
{
  data: <primary result>,
  observations?: [{ kind, text, meta? }],     // → user model writes
  followups?: [{ tool, reason, args_hint? }]  // suggested next tools
}

// Every handler receives
ctx: {
  user_id, conversation_id, recent_tool_calls, user_state,
  audit(action, meta?),
  capture(kind, text, meta?),    // → observations table
  observe(kind, meta),           // → living profile delta
  recall(q, opts?),
  remember(text, kind?, meta?),
  oauth(provider),               // for Category B tools
}
```

---

## 8. File layout (donna-prod target)

```
src/donna/
  brain.ts, prompt.ts, config.ts, voice_filter.ts, tool_kit.ts

  tools/
    core/      logs/      captures/  people/    loops/
    prefs_goals/  reflect/  health/   finance/   writing/
    discovery/  magic/     research/
    integrations/management/   integrations/use/

  clients/                     # one per provider (composio, finnhub, gdelt, etc.)
  proactive/                   # dispatcher, judge, scorer, rate_limit, voice_validator
  integrations/                # IntegrationService (Composio wrapper)
  workers/                     # schedule, poll, watch, integration_sync, dispatcher, synthesis
  ingress/                     # whatsapp + voice/image/document handlers
  delivery/                    # whatsapp out
  memory/                      # supermemory + postgres + recall + chat + users
  observability/
  db/migrations/
  api/webhooks/                # composio, trackingmore, terra, twilio
  api/dashboard/               # GET endpoints

dashboard/                     # Next.js app — 7 sections
```

---

## 9. Conversation history snapshot

For a fresh Claude — here's the arc of decisions made in the original session:

1. **Started with proactive engine review** on `main` and `phase-1-usable` of the python repo. Found Tier 2 + Tier 3 + mirror mode infrastructure.
2. **Rejected tier system** as over-engineered. Decided to collapse to one BRAIN with binary mode flag.
3. **Rejected attention abstraction.** Tools are verbs, not constructors. Reference: Poke (BasedHardware/omi-style simplicity).
4. **Memory: collapsed five backends to two** (Supermemory + Postgres). Single `recall()`.
5. **Designed five-layer source taxonomy** (A/B/C/D/E).
6. **Considered generic primitives, rejected.** Specific prebuilt tools beat generic composition. Most life-tasks have predictable shapes — freeze them.
7. **Researched MCP ecosystem.** 14k+ servers in the registry. MCP servers serve double duty: reactive tools BRAIN calls AND data clients pollers use under the hood. Subscriptions/notifications in spec but barely adopted (Claude Desktop doesn't support, March 2026).
8. **Researched magic APIs.** Locked TrackingMore (not 17track), AirLabs/AviationStack, Terra (unifies wearables), Nutritionix, Wolfram, Foursquare, Veryfi, changedetection.io, Supadata, Exa.
9. **Tool count concern raised.** Reframed: 70 sources don't multiply into 70 tools (most are ambient). Real tool count ~120 with ~15 always-loaded. Deferred via tool_search like Claude Code.
10. **Rejected execution agent and mega-tool.** Coordination via workflow tools + envelope followups + side effects. Three mechanisms.
11. **Confirmed proactive brain needs perception + reasoning + action tools** — not just action. Reactive value is a free side effect of having built the proactive one.
12. **PRD scoped to world engine only.** Original v1 PRD scope-crept; rewritten to ~350 lines covering only the senses layer.

---

## 10. What this doc is for

If you're a fresh Claude continuing this work in donna-prod:

- **Read this first.** Then skim CLAUDE.md (root) for voice rules and PRD-donna-v1.md for the world engine spec.
- **Don't re-propose** the rejected items in section 2.
- **Carry forward** the open questions in section 3 — answer them with evidence, not speculation.
- **Match the principle hierarchy** in section 4. They're ordered by priority.

If you're the human:

- This doc + the PRD + CLAUDE.md = enough context for a fresh session to continue without re-litigating.
- Update this doc as new decisions land. It's the canonical record.

---

End of design decisions.
