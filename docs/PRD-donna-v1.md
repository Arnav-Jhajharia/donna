# Donna v1 — PRD

**Status:** Draft (synthesized from design conversation 2026-05-07)
**Target codebase:** `donna-prod` (TypeScript rewrite). Concepts, contracts, and data model are language-neutral; file paths reference the TS layout.
**Owners:** Arnav

---

## 0. TL;DR

Donna v1 is a WhatsApp-native presence with a single tool-calling brain, one polled+pushed sense layer, one memory layer (Supermemory + Postgres), and a tiered consent surface. No tier system, no orchestrator agent, no attention abstraction. ~35 tools at launch, ~120 in the locked catalog (rest deferred via tool_search). Built to ship in 4 weeks of focused work.

---

## 1. Vision

> Donna is a presence, not an assistant. She holds your life — what's going on, what you said, what you're meant to do, what you're tracking — and never lets anything slip.

Continuity is the product. Reliability is the brand. Every silent failure is brand-damaging.

The dashboard is where she does amazing things with the stuff she's holding. WhatsApp is where she lives.

(For voice, register, and what Donna is/isn't — see CLAUDE.md.)

---

## 2. Principles (locked)

1. **One agent loop.** Sonnet 4.6 ReAct via Anthropic SDK. No LangGraph, no orchestrator agent, no second framework on top of the SDK.
2. **Specific prebuilt tools beat generic primitives** for anything that happens often. Generic verbs (`note`, `generic_watch`, `schedule_check`) exist as fallbacks; the bulk of the catalog is opinionated specific tools.
3. **Tools are verbs, not constructors.** No `create_attention()` or `create_alert()`. `set_price_alert()`, `track_package()`, `remind()`. The verb does the thing; the row is a side effect.
4. **Many tools is fine. Bloated context is not.** ~120 tools in catalog, ~15 always-loaded, the rest discoverable via `tool_search` (lazy schema loading, same pattern as Claude Code).
5. **Memory is two stores: Supermemory + Postgres.** No Graphiti, no bitemporal facts, no five-backend fanout. Supermemory for fuzzy text; Postgres for structured rows; a single `recall()` fans across both.
6. **Workers are dumb. BRAIN is smart. The dispatcher decides when BRAIN wakes.** Pollers and webhooks write to a queue. The Haiku judge filters. BRAIN sees only what survives.
7. **Tools serve perception, reasoning, AND action — not just action.** The proactive brain's quality is upper-bounded by the tool surface. Reactive value comes free as a side effect.
8. **Privacy by default.** Tiered consent at integration connect time (search-only / smart-index / full-index). Default = smart-index with auto-exclusions for banking/medical/legal.
9. **Workflows where you can predict the steps. Autonomy where you can't.** Most life-tasks have known shapes (weekly review, prep_for_meeting, recovery_check_today). Freeze them as single tools. Let BRAIN compose only for genuinely novel requests.
10. **Reliability gates everything.** A reminder that doesn't fire is a betrayal. A voice note not indexed is her not having heard you. Day 1 must work end-to-end.

---

## 3. Architecture overview

```
                    ┌──────────────────────────────────┐
                    │ DATA SOURCES                     │
                    │ ──────────────                   │
                    │ Native APIs    │  MCP servers    │
                    │ (Finnhub,       │  (gdelt-mcp,   │
                    │  GDELT,         │   hn-mcp,      │
                    │  YouTube RSS)   │   alpaca-mcp)  │
                    └─────────┬────────────────┬───────┘
                              │                │
                ┌─────────────┴─────┐    ┌─────┴────────────┐
                │ Pollers           │    │ Webhooks         │
                │ (cron workers)    │    │ (push handlers)  │
                └─────────┬─────────┘    └─────┬────────────┘
                          │                    │
                          ▼                    ▼
                    ┌──────────────────────────────────┐
                    │ raw_items / proactive_events DB  │
                    └────────────────┬─────────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │ Scorer (deterministic + Haiku)   │
                    └────────────────┬─────────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │ BRAIN (Sonnet 4.6 ReAct)         │
                    │  reactive: from user message     │
                    │  proactive: from dispatcher      │
                    │                                  │
                    │  tools (always: 15)              │
                    │  tools (deferred via tool_search)│
                    └────────────────┬─────────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │ Surfaces                         │
                    │  WhatsApp (primary)              │
                    │  Dashboard (rendered views)      │
                    │  Voice/SMS (Twilio, v2)          │
                    └──────────────────────────────────┘
```

Five conceptual layers. No tiers. No mirror modes. No counterfactuals.

---

## 4. Data model — what Donna holds

### 4.1 Two memory stores

**Supermemory (per-user namespace)** — fuzzy/semantic
- past chat messages
- observations ("user mentioned Maya is stressed")
- voice transcripts
- photo captions
- document chunks (PDFs, Drive)
- saved links/articles
- news items (auto-indexed regardless of surfacing)

Single `kind` field tags every entry: `message | thought | link | observation | mood | event | milestone | transcript | caption | doc_chunk | news | rss_item`.

**Postgres** — structured

### 4.2 Postgres tables

```sql
-- core identity & comms
users(id, phone, timezone, created_at, ...)
chat_messages(id, user_id, role, text, is_proactive, created_at, embedding)

-- the soft user-model layer (free-form observations)
observations(id, user_id, kind, text, meta jsonb, created_at, source_tool)

-- structured personal logs (one table per kind for clean schemas)
expenses(id, user_id, amount, currency, category, vendor, note, occurred_at)
calorie_log(id, user_id, food, qty, kcal, macros jsonb, eaten_at)
workout_log(id, user_id, activity, duration_min, intensity, source, occurred_at)
sleep_log(id, user_id, hours, quality_1_10, source, slept_at)
mood_log(id, user_id, mood, intensity_1_10, context, logged_at)
energy_log(id, user_id, level_1_10, context, logged_at)
water_log(id, user_id, oz, logged_at)
substance_log(id, user_id, item, qty, kind, logged_at)  -- caffeine, alcohol, etc.
weight_log(id, user_id, value, unit, logged_at)
med_log(id, user_id, name, dose, taken_at)

-- people + relationships
people(id, user_id, name, relationship, created_at)
person_attributes(person_id, key, value, updated_at)  -- birthday, job, pets, kids, etc.
person_meetings(id, person_id, summary, occurred_at)

-- commitments
loops(id, user_id, text, person_id?, due?, status, opened_at, closed_at?, resolution?)

-- preferences + goals
preferences(user_id, key, value, updated_at)
goals(id, user_id, text, deadline?, kind, progress jsonb, created_at)

-- attention (the universal "things to come back to" — replaces DonnaSchedule + reminders + open_loops)
scheduled_jobs(
  id, user_id, kind, trigger jsonb, what text, status, route_ref?,
  created_at, fire_at?, last_run_at?, next_run_at?
)

-- watches (typed sub-kinds of scheduled_jobs for high-frequency monitoring)
watches(
  id, user_id, kind, ref jsonb, state jsonb, status,
  cadence_seconds, last_polled_at, last_fired_at
)

-- ingestion
raw_items(id, user_id?, source, source_ref, title, content, url, meta jsonb, fetched_at)
dedup_ledger(user_id, ref_hash, seen_at)  -- 7-day TTL
proactive_events(id, user_id, source, source_ref, score, signals jsonb, status, payload jsonb)
proactive_pings(id, user_id, topic_key, source, fired_at, suppressed_reason?)

-- integrations
integrations(user_id, provider, status, mode, config jsonb, composio_account_id?,
             last_sync_at?, last_error jsonb?, connected_at)
integration_audit(user_id, provider, action, item_ref, occurred_at, meta jsonb)

-- routes (capability → integration mapping)
routes(user_id, capability, provider, resource_ref?, config jsonb, set_at)

-- user-managed feeds (RSS, YouTube channels, Reddit subs, etc.)
feeds(user_id, kind, ref, label, active, added_at)

-- distilled "who you are right now"
living_profile(user_id, body jsonb, updated_at)
```

### 4.3 Living profile (JSONB)

The distilled top-of-mind summary, written by the synthesis worker, read into BRAIN's USER MODEL block every turn.

```json
{
  "summary": "...",
  "top_of_mind": ["...", "..."],
  "recent_state": "stressed week, sleep down",
  "interests": ["nyc politics", "anthropic releases", "philosophy"],
  "watches": ["NVDA", "warriors", "anthropic news"],
  "preferences": {
    "morning_brief_time": "07:00",
    "journal_voice": "first_person_brief",
    "weekend_quiet_hours": true
  },
  "watch_for_tomorrow": ["..."],
  "today_shape": "..."
}
```

---

## 5. Tools — BRAIN's surface

### 5.1 Surface count

```
Always loaded:                  ~15
Deferred (catalog):             ~105
─────────────────────────────────────
Total:                          ~120
```

Always-loaded keeps per-turn tool schema cost ~2k tokens. Deferred discovered via `tool_search()`.

### 5.2 Always-loaded primitives (15)

```ts
send(text: string)
ask(question: string)                   // pause turn, wait for user
ack(intent?: string)                    // tiny acknowledgment
recall(query, kind?, person?, time?)
remember(text, kind?, meta?)
note(kind, text, meta?)                 // observation/thought/mood/event/milestone
get_user_state()                        // snapshot of living profile
search_web(query, freshness?)           // Exa-backed agentic
web_search(query)                       // raw SERP fallback
schedule_check(when_or_cron, what)      // universal fallback for proactive
generic_watch(what, source, cadence, trigger, on_fire)  // ad-hoc monitoring
remind(when, text)                      // one-shot
remind_recurring(cron, text)            // recurring
tool_search(query)                      // discover deferred tools
cancel(id)                              // stop scheduled job / watch / reminder
```

### 5.3 Deferred — Personal logs (10)

```
log_expense(amount, category?, vendor?, note?)
log_calories(food, qty?, kcal?)
log_workout(activity, duration_min, intensity?)
log_sleep(hours, quality?, note?)
log_mood(mood, intensity?, context?)
log_energy(level_1_10, context?)
log_water(oz)
log_substance(item, qty?)
log_weight(value, unit)
log_med(name, dose?)
```

### 5.4 Deferred — Captures (5)

```
capture_link(url)                       // fetches title + summary + og-image, indexes
capture_quote(text, source?)
capture_idea(text, tag?)
capture_recipe(text_or_url)
capture_book(title, author?)            // OpenLibrary lookup
```

### 5.5 Deferred — People (10)

```
person_note(name, observation, relationship?)
person_update(name, key, value)
person_recall(name)
person_list(filter?)
person_last_touch(name)
person_note_meeting(name, summary)
draft_message_to(person, intent)
schedule_with(person, prefs?)
last_convo_with(person)
prep_for_meeting(person_or_event)
```

### 5.6 Deferred — Loops (4)

```
loop_open(text, person?, due?)
loop_close(id, resolution?)
loop_list(status?, person?)
loop_aging()                            // oldest open loops, used by proactive
```

### 5.7 Deferred — Prefs / Goals (5)

```
pref_set(key, value)
pref_get(key)
goal_set(text, deadline?)
goal_update(id, progress?, note?)
goal_list()
```

### 5.8 Deferred — Reflection workflows (8)

```
reflect(window)                         // "what's user been about lately"
summarize_day(date?)
summarize_week()
weekly_review()                         // composed summary, written to Notion route
month_in_review(month?)
get_pattern(topic)
get_aggregate(metric, range)
relationship_check_in(person?)
```

### 5.9 Deferred — Health workflows (4)

```
recovery_check_today()                  // pulls Whoop via Terra
training_load(window?)
correlate_sleep_mood(window?)
nutrition_breakdown(meal_text)          // Nutritionix-backed
```

### 5.10 Deferred — Finance workflows (3)

```
spend_check(category?, window?)
recurring_charges_review()
budget_status()
```

### 5.11 Deferred — Writing aids (4)

```
draft_email_in_voice(intent)
draft_message_in_voice(intent)
edit_for_brevity(text)
summarize_thread(thread_id)
```

### 5.12 Deferred — Discovery (4)

```
find_restaurant_for(occasion, prefs?)
find_book_like(book_or_topic)
find_movie_for(mood, length?)
find_recipe_for(ingredients_or_diet)
```

### 5.13 Deferred — Magic verbs / specific watches (16)

```
track_package(tracking_no, carrier?)
track_flight(flight_no, date?)
set_price_alert(symbol, op, value)
poll_score(team)
follow_topic(query, freshness?)
watch_repo_release(github_repo)
watch_artist_release(spotify_artist_id_or_name)
watch_substack(author_url)
watch_youtube_channel(channel_id_or_handle)
watch_price_drop(product_url, target?)
watch_concert(artist, city)
watch_cheap_flight(from, to, window)
find_places(query, near?, open_now?)
compute_math(question)                  // Wolfram
parse_receipt(image_url)                // Veryfi
transcribe_video(url)                   // Supadata
watch_url(url, change_kind?)            // changedetection.io
```

### 5.14 Deferred — Single-call utilities (8)

```
stock_price(symbol)
crypto_price(symbol)
news_search(q, window?)                 // GDELT
weather_at(location, when?)
top_hn(category?)
score_of(team)
translate(text, lang)
research_topic(query, depth?)           // multi-source synthesis
```

### 5.15 Deferred — Integration management (9)

```
integration.connect(provider)
integration.status(provider?)
integration.set_mode(provider, mode)
integration.add_exclusion(provider, kind, value)
integration.start_sync(provider)
integration.disconnect(provider)
route.set(capability, provider, ref?)
route.get(capability)
route.list()
```

### 5.16 Deferred — Integration use (12)

```
gmail.search(query)
gmail.draft(thread_id, body)
gmail.send(to, subject, body)
gcal.list(range)
gcal.create(event)
gcal.update(event_id, changes)
notion.append(page_or_db, content)
notion.search(query)
spotify.recent()
readwise.recent_highlights()
health.metric(metric, range?)           // Terra-backed
strava.recent()
```

### 5.17 Tool contract

Every tool exports `{ name, description, schema, handler, loaded, tags }`.

**Description discipline (mandatory):** every tool description includes:
- one-line what it does
- USE WHEN clause
- DO NOT USE FOR clause
- input/output shape

**Return envelope (mandatory):**

```ts
{
  data: <primary result>,
  observations?: [{ kind, text, meta? }],   // explicit user-model writes
  followups?: [{ tool, reason, args_hint? }] // suggested next tools (BRAIN may chain)
}
```

**Handler context (passed to every handler):**

```ts
ctx: {
  user_id: string,
  conversation_id: string,
  recent_tool_calls: ToolCall[],            // last N this turn
  user_state: LivingProfile,                // snapshot

  audit(action: string, meta?: any): void,
  capture(kind: string, text: string, meta?: any): Promise<void>,  // → observations
  observe(kind: string, meta: any): void,   // → living profile delta
  recall(query: string, opts?: any): Promise<RecallResult[]>,
  remember(text: string, kind?: string, meta?: any): Promise<void>,
  oauth(provider: string): Promise<Token>,  // for Category B tools
}
```

### 5.18 Coordination — three mechanisms only

1. **Inside specific workflow tools** (frozen sequences). `weekly_review` calls 5 things internally; BRAIN sees one tool.
2. **Return envelope hints** (`followups`). Tool suggests next steps; BRAIN chooses.
3. **Side effects** (`ctx.capture`, `ctx.observe`). User-model state updates without BRAIN reasoning about it.

No execution agent. No mega-tool. No DSL.

---

## 6. Data sources — Donna's senses

### 6.1 Layer A: World substrate (universal pollers)

Run once for everyone. Filtered per-user by interests in the scorer.

| Source | Cadence | Implementation | Cost |
|---|---|---|---|
| GDELT 2.0 | 30 min | GDELT MCP or direct | Free |
| Hacker News | 15 min | HN MCP (community) | Free |
| NewsAPI aggregator (27 outlets bundled) | 30 min | Apify NewsAggregator MCP | Free |
| Product Hunt | daily | PH MCP | Free |
| arXiv (per category) | daily | RSS direct | Free |
| Substack popular feeds | hourly | RSS direct | Free |
| Federal Reserve / Treasury | daily | Direct API | Free |
| Trending GitHub repos | daily | GitHub MCP | Free |

### 6.2 Layer B: User-specific watches (per-user, per-thing)

| Source | Cadence | Implementation |
|---|---|---|
| User RSS | 30 min | Generic RSS MCP |
| YouTube channels | 30 min | YouTube RSS direct + WebSub option |
| Reddit subs | 30 min | Reddit JSON or MCP |
| GitHub releases (watched repos) | daily | GitHub MCP |
| Linear/Jira (assigned issues) | hourly | Linear/Jira MCP |
| Stock prices (per ticker) | 5 min during market | Finnhub or Alpaca MCP |
| Crypto (per coin) | 5 min | CoinGecko MCP |
| SEC filings | daily | EDGAR direct |
| Sports (per team) | 5 min during games | API-Sports or TheSportsDB |
| Weather forecast | hourly | OpenWeather |
| NWS severe alerts | every 10 min in zone | NWS direct |
| Package tracking | 4hr exp backoff + webhook | TrackingMore |
| Flight tracking | 30 min during travel | AirLabs |
| URL change detection | per-watch | changedetection.io |
| Cheap flight watcher | daily | Kiwi/Skyscanner |
| Concert availability | hourly | Ticketmaster |
| congress.gov bills (per topic) | daily | direct |

### 6.3 Layer C: Per-integration sync (fallback when no webhook)

| Integration | Cadence | Implementation |
|---|---|---|
| Gmail incremental | 15 min (webhook preferred) | Composio Gmail MCP |
| Calendar incremental | 15 min (webhook preferred) | Composio Calendar MCP |
| Notion page changes | hourly | Official Notion MCP |
| Health (Terra) | daily + webhook | Terra direct |
| Strava activity | hourly | Strava MCP |
| Spotify recent | 30 min | Spotify MCP |
| Readwise daily review | daily | Readwise API |

### 6.4 Layer D: Webhooks (push)

| Source | Trigger |
|---|---|
| Composio (Gmail/Calendar/Notion) | content change |
| TrackingMore | package status push |
| Terra | new health data |
| YouTube WebSub | new channel upload |
| Apple Shortcuts | user-initiated push |
| Twilio inbound | SMS/voice |
| Cal.com / Calendly | booking |

### 6.5 Layer E: Reactive-only (called per BRAIN turn)

| Source | Use | Implementation |
|---|---|---|
| Wolfram Alpha | math/units/computation | direct |
| Exa | semantic search (primary) | Exa MCP or direct |
| Tavily | general search (fallback) | direct |
| Foursquare Places | restaurants/POIs | Foursquare MCP |
| Nutritionix | food/calorie lookup | direct |
| Veryfi | receipt OCR | direct |
| Supadata | YouTube transcripts | direct |
| TheMovieDB | movie metadata | direct |
| Open Library | book metadata | direct |
| Translate (Google/DeepL) | language conversion | direct |

### 6.6 MCP vs direct API decision

- **Use MCP servers** when one exists with reasonable quality (most news, most finance, most consumer integrations). Same wrapper serves both pollers and reactive tools.
- **Direct API** for Donna-specific magic (TrackingMore, Veryfi, Wolfram, Nutritionix) where wrapping value is in our code, not the source.
- **Composio** for OAuth integrations (Gmail/Calendar/Notion). One auth gateway.
- **Webhooks** wherever push is supported. Always preferred over polling.

---

## 7. Workers

```
src/donna/workers/
  schedule_worker.ts        # fires due rows in scheduled_jobs (reminders, recurring, watches)
  poll_worker.ts            # cadence-driven, runs world + user-watch pollers
  integration_sync.ts       # gmail/calendar incremental sync (when no webhook)
  proactive_dispatcher.ts   # drains proactive_events, scores, may invoke BRAIN
  synthesis_worker.ts       # nightly living-profile rebuild + morning brief
```

Each runs as its own process (Railway service). No shared memory. Coordinate via Postgres.

### 7.1 Cadences

```
10s     schedule_worker tick
10s     proactive_dispatcher tick

5min    stock watches (market hours)
5min    sports watches (game windows)
5min    crypto watches

15min   HN poll
15min   gmail incremental (fallback)
15min   gcal incremental (fallback)

30min   GDELT poll
30min   user RSS poll
30min   YouTube RSS poll (per channel)
30min   Reddit poll (per sub)
30min   flight tracking (active travel)

hourly  weather forecast (per location)
hourly  Notion page changes
hourly  Strava

4hr     package tracking (exp backoff toward delivery)

daily   arXiv per category
daily   Health (Terra) full sync
daily   Readwise daily review
daily   morning brief composer (per user, near their first-engage time)

weekly  weekly review composer (per user, Sunday 7pm local default)
nightly synthesis worker full pass (per user, ~02:00 local)
```

---

## 8. Proactive pipeline

### 8.1 Flow

```
external event → (poller writes to raw_items / webhook handler writes to proactive_events)
              → pre-score (deterministic): keyword overlap with user.interests + watches + open_loops + recency
              → drops ~90% as noise
              → Haiku judge (only on survivors): {action, register, draft, tie_in, needs_tools}
              → action=drop  → record suppressed_reason
                action=hold  → PendingProactiveNote (12h TTL)
                action=ship  → voice_validator → ship_draft → WhatsApp + ChatMessage + ProactivePing
                action=escalate (needs_tools)  → BRAIN(proactive)
              → BRAIN(proactive) uses tools, returns send_burst or stays silent
```

### 8.2 Rate limiting (locked from existing)

- Daily quota: 3/user/day (env-tunable)
- Global cooldown: 30 min
- Per-topic cooldown: 30 min (keyed on `topic_key`)
- Quiet hours: user.preferences.sleep_time/wake_time, fallback 00:00–07:00 local
- Active-chat suppression: deny if user messaged in last 5 min
- Per-integration dedup: hash of source_ref or normalized URL, 7-day TTL

### 8.3 Mode flag

`mode: "reactive" | "proactive"` — actually used now (not cosmetic).

Differences:
- Different prompt suffix (`proactive` includes trigger context, register guidance)
- Stateless sessions for proactive (no chat history poisoning)
- On error: proactive returns `_outbound = []` silently (no "hm one sec" ack)
- `proactive_max_turns = 12` (vs reactive 6) — wired through, not just declared

No `tier3` mode. No mirror counterfactual.

---

## 9. Privacy & consent

### 9.1 Tiered consent per integration

At connect time, Donna asks (in voice, on WhatsApp):

```
Mode 1: Search-only
  Donna stores nothing. Searches your inbox/calendar live when needed.

Mode 2: Smart-index (DEFAULT)
  Indexes content, automatically excluding labels/senders matching:
    - banking, finance, medical, legal, confidential
    - OTPs, password resets, magic links

Mode 3: Full-index
  Everything, no exclusions. Explicit opt-in only.
```

User can change mode anytime via `integration.set_mode()`. Mode change → re-index or wipe job.

### 9.2 Always-on controls

- "donna, forget this email" → purges by message_id
- "donna, forget everything from <sender>" → bulk purge
- "donna, never index emails labeled <label>" → adds exclusion
- Dashboard: toggle mode, exclusion editor, indexed-count, "wipe data" button

### 9.3 Compliance posture (v1)

- **Free tier**: security.txt, public privacy page, public subprocessor list, CSA STAR Level 1 self-assessment, responsible-disclosure email
- **Vendor**: Zero-Data-Retention agreement with Anthropic (free, must sign)
- **Database**: Postgres RLS enforced at every table; sensitive fields encrypted at rest with libsodium (OAuth tokens, integration creds)
- **Audit**: every integration call writes to `integration_audit` with item_ref + user_id
- **Export + delete from day 1**: dashboard buttons, must work end-to-end
- **No third-party analytics on user data**: PostHog/Segment/etc. get only event names + counts, never message content

Deferred to v2: SOC 2 Type 1, per-user envelope encryption, BYOK, confidential inference.

---

## 10. Surfaces

### 10.1 WhatsApp (primary)

Already wired in `donna-prod`. Webhook ingress, Twilio outbound. Voice rules in system prompt.

### 10.2 Dashboard (Next.js, simple)

Seven sections, each a SQL query against existing tables:

```
TODAY
  - calendar.list(today + tomorrow)
  - reminders firing today (scheduled_jobs WHERE fire_at::date = today)
  - watches that fired today (proactive_pings WHERE date = today)

LIFE                                ← weekly aggregates rendered as cards
  - spend (this week, by category)
  - mood (last 7 days, simple sparkline)
  - sleep (last 7 days, vs Whoop if connected)
  - workouts (count, total minutes)

PEOPLE                              ← relationship surface
  - top N people by recency, with last_touch + open loops summary

LOOPS
  - open loops, oldest at top, grouped by person if applicable

WATCHING
  - active watches: price alerts, tracked packages, followed topics, etc.

GOALS
  - active goals with progress bars

NOTE                                ← today's editorial
  - generated by synthesis worker, one paragraph

INTEGRATIONS                        ← settings, not a daily surface
  - connected providers, status, mode, exclusions, audit log, wipe button

RECALL                              ← search bar, hits Supermemory + structured tables
```

No 21-archetype catalogue. No bespoke editorial cards. Just the user's data made visible.

### 10.3 Voice/SMS (deferred to v2)

Twilio substrate exists. Real implementation in v2.

---

## 11. v1 scope

### 11.1 Locked for v1 ship

**Tools (~35):**
- All 15 always-loaded primitives
- All 10 personal logs
- 5 most-used reflection: `reflect`, `summarize_day`, `weekly_review`, `get_pattern`, `relationship_check_in`
- 5 magic verbs: `track_package`, `set_price_alert`, `compute_math`, `find_places`, `parse_receipt`
- 5 captures: all of them
- People: `person_note`, `person_recall`, `person_last_touch`, `prep_for_meeting`, `draft_message_to`
- Loops: all 4
- 4 integration management: `integration.connect/status/set_mode/disconnect`
- 6 integration use: `gmail.search/draft/send`, `gcal.list/create/update`

**Data sources:**
- World substrate: GDELT, HN, RSS (user), Finnhub, OpenWeather, CoinGecko (6)
- User watches: stock alerts, package tracking, YouTube channels, URL change, sports, follow_topic (6 kinds)
- Integrations: Gmail + Calendar (Composio)
- Reactive: Exa, Wolfram, Foursquare, Nutritionix, Veryfi (5)
- Webhooks: Composio (Gmail/Calendar), TrackingMore, Twilio inbound

**Surfaces:**
- WhatsApp ingress + egress (already in donna-prod)
- Dashboard: TODAY, LIFE, LOOPS, WATCHING, NOTE, RECALL, INTEGRATIONS

**Privacy:**
- Tiered consent (mode 1/2/3) with default = mode 2
- Auto-exclusions for Gmail (banking/medical/legal regex + label match)
- Export + delete buttons functional

### 11.2 Deferred to v2

- Health (Terra) integration
- Notion, Spotify, Readwise, Strava integrations
- Plaid (banking)
- Voice (Twilio Conversations)
- Remaining magic verbs (Supadata, transcribe_video, watch_concert, etc.)
- Reflection workflows beyond the 5 above
- All discovery tools (find_restaurant_for, etc.)
- Writing aids
- Health workflows (recovery_check_today, etc.)
- More world substrate (Product Hunt, arXiv, GitHub trending, Substack popular)
- More user watches (cheap flights, concerts, restaurant availability, etc.)

### 11.3 Day-1 reliability gates

These must work, not "should work after the user texts again":

- `remind` fires within 60s of `fire_at` always — else alert
- Synthesis worker runs nightly for every active user — else alert
- Voice notes inbound → STT → searchable in Supermemory within 5 min
- Photos inbound → captioned + searchable within 5 min
- Documents inbound → chunked + searchable within 10 min
- Backfill on Gmail connect completes within 15 min (90 days) — else alert
- All proactive sends pass voice_validator (no uppercase/emoji/em-dash/semicolon)

---

## 12. File structure (donna-prod target)

```
src/donna/
  brain.ts                           # Sonnet ReAct loop
  prompt.ts
  config.ts
  voice_filter.ts
  tool_kit.ts                        # defineTool, ctx, registry, tool_search

  tools/
    index.ts                         # full registry export
    core/                            # always-loaded (15 files)
      send.ts, ask.ts, ack.ts, recall.ts, remember.ts, note.ts,
      get_user_state.ts, search_web.ts, web_search.ts, schedule_check.ts,
      generic_watch.ts, remind.ts, remind_recurring.ts, tool_search.ts, cancel.ts
    logs/                            # personal logs (10)
    captures/                        # captures (5)
    people/                          # people verbs (10)
    loops/                           # commitments (4)
    prefs_goals/                     # prefs + goals (5)
    reflect/                         # reflection workflows (8)
    health/                          # health workflows (4)
    finance/                         # finance workflows (3)
    writing/                         # writing aids (4)
    discovery/                       # discovery (4)
    magic/                           # specific watches + utilities (24)
    research/                        # research_topic, deep_dive
    integrations/
      management/                    # connect, set_mode, etc. (9)
      use/                           # gmail.*, gcal.*, etc. (12)

  clients/                           # one file per provider
    composio.ts                      # OAuth gateway wrapper
    finnhub.ts, gdelt.ts, hn.ts, rss.ts, openweather.ts, coingecko.ts,
    apisports.ts, exa.ts, tavily.ts, wolfram.ts, foursquare.ts,
    nutritionix.ts, veryfi.ts, supadata.ts, trackingmore.ts, airlabs.ts,
    changedetection.ts, terra.ts, youtube.ts, readwise.ts,
    gmail.ts (via composio), gcal.ts (via composio), notion.ts (via composio)
    search.ts                        # fan-out/fallback over exa+tavily

  proactive/
    dispatcher.ts                    # drains proactive_events, runs scorer + judge
    judge.ts                         # Haiku call, returns {action, draft, ...}
    scorer.ts                        # deterministic pre-scorer
    rate_limit.ts                    # quota + cooldown + quiet hours + active-chat
    voice_validator.ts               # uppercase/emoji/em-dash check + reauthor

  integrations/                      # the IntegrationService (Composio wrapper layer)
    service.ts                       # the class: connect/refresh/state/audit
    consent.ts                       # tiered consent flow + exclusion application
    state.ts                         # CRUD on integrations table
    routes.ts                        # CRUD on routes table
    audit.ts
    errors.ts                        # → ProactiveEvent emission
    backfill.ts                      # generic backfill driver
    sync.ts                          # generic incremental sync driver

  workers/
    schedule_worker.ts
    poll_worker.ts
    integration_sync.ts
    proactive_dispatcher.ts
    synthesis_worker.ts

  ingress/
    whatsapp.ts                      # already exists
    voice.ts                         # STT for voice notes
    image.ts                         # caption for images
    document.ts                      # chunk + embed PDFs

  delivery/
    whatsapp.ts                      # already exists

  memory/
    supermemory.ts                   # add/search wrapper
    postgres.ts                      # structured-table helpers
    recall.ts                        # unified read across both
    chat.ts                          # already exists
    users.ts                         # already exists

  observability/
    langsmith.ts                     # already exists
    audit.ts

  db/
    migrations/
    schema.ts                        # all table definitions

  api/
    webhooks/
      composio.ts                    # gmail/gcal/notion push
      trackingmore.ts
      terra.ts
      youtube_websub.ts
      twilio.ts                      # SMS/voice inbound (v2)
    dashboard/                       # GET endpoints feeding the UI
    integrations/                    # OAuth callbacks

dashboard/                           # Next.js app
  app/
    today/
    life/
    people/
    loops/
    watching/
    note/
    recall/
    integrations/
```

---

## 13. Implementation phases

### Phase 1 — Foundation (week 1)
- Postgres schema + migrations for all tables
- Supermemory client + unified `recall()` + `remember()`
- `tool_kit.ts`: defineTool, ctx, registry, tool_search
- 15 always-loaded primitives end-to-end
- WhatsApp ingress + egress wired (mostly exists)
- BRAIN loop with reactive mode

### Phase 2 — User-model layer (week 2)
- 10 personal log tools + tables
- 5 captures
- 5 people tools (the most-used)
- 4 loop tools
- Side-effect hooks (`ctx.capture`, `ctx.observe`)
- Synthesis worker (nightly living profile rebuild)

### Phase 3 — Proactive engine (week 3)
- `proactive/` directory: dispatcher, judge, scorer, rate_limit, voice_validator
- `scheduled_jobs` table + schedule_worker
- `watches` table + watch_worker
- Proactive mode wired in BRAIN
- 5 magic verbs: track_package, set_price_alert, compute_math, find_places, parse_receipt
- 6 user-watch kinds
- World substrate pollers (6 sources)
- Webhook handlers (TrackingMore, Composio)

### Phase 4 — Integrations + dashboard (week 4)
- `IntegrationService` + Composio wrapper
- Tiered consent flow on connect
- Gmail integration (search/draft/send + smart-index backfill)
- Calendar integration (list/create/update)
- 4 integration-management tools + 6 integration-use tools
- Dashboard: 7 sections, all backed by SQL queries
- Privacy controls: export, delete, exclusion editor
- Day-1 reliability gates verified

---

## 14. Open questions

1. **Composio vs direct OAuth?** Composio is faster to ship + maintains tokens, but is paid and adds a hop. Direct OAuth means we own the auth surface. Recommendation: Composio for v1, can swap internally without changing tools.

2. **MCP servers vs hand-crafted clients?** For v1 I'd prefer hand-crafted for the magic 5 (TrackingMore, Veryfi, Wolfram, Nutritionix, Foursquare) because we want voice-controlled wrapping. MCP for breadth in v2 (n8n long-tail, GitHub, Linear, etc.).

3. **Tool catalog hosting.** In-process registry works for v1. Externalize to a database when catalog crosses ~200 or when team contributors emerge.

4. **Embedding provider for memory.** Supermemory handles embeddings internally — we don't choose. But for the structured Postgres `chat_messages.embedding` column, we'd use OpenAI text-embedding-3-small or Voyage. Recommendation: Voyage 3 for quality, OpenAI for fallback.

5. **Voice in v1?** Currently deferred to v2 per scope above. If user demand emerges, Twilio Conversations is the substrate. Defer for now.

6. **Dashboard tech.** Next.js (existing) is fine. No special design system needed at v1 — donna-design-system can be deferred.

7. **Reasoning model choice.** Sonnet 4.6 across all reactive + proactive turns. Haiku 4.5 inside specific lanes (post-turn user-fact extractor, Tier 2 proactive judge, awareness scoring, image captioning).

8. **Cost discipline target.** Reactive turn ~$0.02-0.05. Proactive fire ~$0.01-0.03 (if it survives the cheap path). Per-user/day target: $0.20-0.40.

9. **Routes — where outputs go.** Capabilities (daily_journal, weekly_review, expense_log) route to integrations or fall back to `donna_native` (lives in Postgres). User picks via `route.set` at first-use or at integration connect.

10. **Auto-exclusion list for Gmail smart-index.** Initial defaults:
    - Labels: `Banking`, `Finance`, `Medical`, `Legal`, `Confidential`
    - Senders: `*@*bank*`, `*@*hospital*`, `*@*law*`, etc. (heuristic — refine)
    - Subjects matching: `(?i)(otp|verification code|password reset|magic link)`
    - Lock with editable list in dashboard from day 1.

---

## 15. What this is not

- Not a tier system. No Tier 2 / Tier 3.
- Not a workflow engine. No DSL for jobs.
- Not a multi-agent system. One BRAIN.
- Not a graph database. No Graphiti, FalkorDB.
- Not bitemporal. Just normal Postgres timestamps.
- Not a "thinking partner who debates you." Voice register stays per CLAUDE.md.
- Not a productivity tool. Doesn't draft documents, run a CRM, replace an EA.
- Not a therapist. Soft register exists, but route to professional support when needed.

---

## 16. Done criteria for v1

- [ ] User can text Donna on WhatsApp, get a response in <3s for reactive turns
- [ ] All 15 always-loaded tools work end-to-end with audit logs
- [ ] All 10 personal log tools functional with side-effect captures
- [ ] Connect Gmail → tiered consent dialog → backfill 90 days with auto-exclusions → searchable via `recall`
- [ ] Connect Calendar → events readable, creatable, updateable
- [ ] `track_package` works for at least UPS/USPS/FedEx via TrackingMore
- [ ] `set_price_alert` fires within 5 min of threshold cross during market hours
- [ ] `remind("call mom tomorrow at 6")` fires at exactly the right local time
- [ ] Proactive engine: morning brief composer fires once per user per local day, only if conditions met
- [ ] Quiet hours respected (no proactive sends 00:00-07:00 local)
- [ ] Daily quota enforced (3/day default)
- [ ] Dashboard renders all 7 sections with real data
- [ ] Export-all and delete-all buttons functional
- [ ] Voice validator catches uppercase/emoji/em-dash/semicolon in proactive sends
- [ ] All integration calls audited
- [ ] Living profile rebuilt nightly per user
- [ ] No silent failures: any reminder/sync/backfill that misses its SLA emits an alert

---

End of PRD.
