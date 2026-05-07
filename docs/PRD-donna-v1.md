# Donna — World Engine PRD

**Status:** Draft (2026-05-07)
**Scope:** The senses layer only — data sources, APIs, MCPs, pollers, webhooks, and the pipeline that delivers world events into BRAIN. Excludes user model, tool catalog beyond source-wrappers, dashboard, voice/register, onboarding.
**Target codebase:** `donna-prod` (TypeScript). Concepts language-neutral.

---

## 0. TL;DR

The world engine is what Donna sees and hears. It pulls structured data from ~30 sources via a mix of direct APIs and MCP servers, ingests it through pollers and webhooks, scores it cheaply, and surfaces only what matters to the user via the proactive lane. A subset of these sources is also exposed as reactive tools BRAIN can call on demand.

The brain itself is out of scope for this doc. This PRD locks **how the world enters Donna**.

---

## 1. Why this layer matters

The proactive brain's quality is upper-bounded by the breadth and freshness of the senses. If Donna only sees user messages, she's a chatbot. If she also sees stock movements, package events, calendar conflicts, news intersecting interests, sleep data, weather alerts — she's a presence.

Every tool BRAIN calls is also a sense. Reactive tools (`stock_price`, `news_search`, `compute_math`) and ambient pollers (`gdelt_poller`, `stock_watcher`) share the same client layer. One integration, two consumption patterns.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Data sources                                             │
│  ────────────────────────────────────────────────────── │
│  Direct APIs                  │  MCP servers              │
│   (Finnhub, GDELT,            │  (gdelt-mcp, hn-mcp,     │
│    YouTube RSS, Wolfram,      │   alpaca-mcp,            │
│    TrackingMore, Veryfi, etc.)│   foursquare-mcp, etc.)  │
└────────────────┬───────────────────────────┬─────────────┘
                 │                           │
        ┌────────┴────────┐         ┌────────┴────────┐
        │  Pollers         │         │  Webhook         │
        │  (cron workers)  │         │  handlers        │
        └────────┬────────┘         └────────┬────────┘
                 │                           │
                 ▼                           ▼
        ┌────────────────────────────────────────────┐
        │  raw_items + proactive_events DB           │
        └──────────────────────┬─────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  Scorer (deterministic + Haiku judge)      │
        └──────────────────────┬─────────────────────┘
                               │ (only what survives)
                               ▼
        ┌────────────────────────────────────────────┐
        │  BRAIN(proactive)  +  reactive tool calls  │
        └────────────────────────────────────────────┘
```

Pollers and webhooks write to `raw_items` and `proactive_events`. The scorer drops noise. BRAIN sees only what survives. Reactive tools wrap the same clients for on-demand calls.

---

## 3. Five source layers

| Layer | What | Pattern |
|---|---|---|
| **A** | World substrate (universal feeds) | Polled, shared across all users |
| **B** | User-specific watches | Polled, per-user per-watched-thing |
| **C** | Per-integration sync (Gmail/Calendar/etc.) | Polled fallback when no webhook |
| **D** | Webhooks | Pushed real-time |
| **E** | Reactive-only sources | Called per BRAIN turn, never polled |

---

## 4. Layer A — World substrate (universal pollers)

Run once for everyone. Per-user filtering happens in the scorer against `interests`, `watches`, and `loops`.

| Source | Cadence | Implementation | Cost |
|---|---|---|---|
| GDELT 2.0 | 30 min | GDELT MCP (Apify) or direct | Free |
| Hacker News | 15 min | HN MCP (community) | Free |
| NewsAPI aggregator (Reuters/AP/BBC/Bloomberg/CNN — 27 outlets) | 30 min | Apify NewsAggregator MCP | Free |
| Product Hunt | daily | PH MCP | Free |
| arXiv (per category) | daily | RSS direct | Free |
| Substack popular | hourly | RSS direct | Free |
| Federal Reserve / Treasury releases | daily | Direct API | Free |
| Trending GitHub repos | daily | GitHub MCP (official) | Free |

**v1 ships:** GDELT, HN, NewsAPI aggregator, Federal Reserve.
**Defer to v2:** Product Hunt, arXiv, Substack popular, GitHub trending.

---

## 5. Layer B — User-specific watches

Per-user, per-watched-thing. Cadence varies by source. Each watch is a row in `watches`.

### Personal interest feeds
| Source | Cadence | Implementation |
|---|---|---|
| User RSS (any URL) | 30 min | Generic RSS MCP |
| YouTube channels (per channel) | 30 min | YouTube RSS direct + WebSub option |
| Reddit subs | 30 min | Reddit JSON or community MCP |
| Mastodon/Bluesky timeline | 15 min | community MCP |
| Substack authors followed | hourly | RSS direct |

### Code & work
| Source | Cadence | Implementation |
|---|---|---|
| GitHub releases (watched repos) | daily | GitHub MCP |
| GitHub mentions of user | hourly | GitHub MCP |
| Linear assigned issues | hourly | Linear MCP |
| Jira assigned tickets | hourly | Jira MCP |
| Slack mentions | webhook preferred, hourly poll fallback | Slack MCP |

### Markets
| Source | Cadence | Implementation |
|---|---|---|
| Stock prices (per ticker) | 5 min during market hours | Finnhub direct or Alpaca MCP |
| Crypto (per coin) | 5 min | CoinGecko MCP |
| SEC EDGAR filings (per company) | daily | EDGAR direct |
| Earnings calendar (per ticker) | daily | Finnhub |

### Sports
| Source | Cadence | Implementation |
|---|---|---|
| API-Sports (per team) | 5 min during games | API-Sports MCP |
| Football-Data.org (soccer) | 5 min during games | Direct API (free for major leagues) |

### Weather & environment
| Source | Cadence | Implementation |
|---|---|---|
| OpenWeather forecast | hourly | OpenWeather MCP |
| NWS severe alerts (US) | every 10 min in active zones | NWS direct |
| AirVisual air quality (per city) | hourly | AirVisual API |

### Travel & logistics
| Source | Cadence | Implementation |
|---|---|---|
| TrackingMore (per active package) | 4hr exp backoff + webhook | TrackingMore direct |
| AirLabs (per active flight) | 30 min during travel | AirLabs direct or MCP |
| Cheap flight watcher (per route) | daily | Kiwi/Skyscanner MCP |
| Concert availability (per artist+city) | hourly | Ticketmaster MCP |

### Civic
| Source | Cadence | Implementation |
|---|---|---|
| congress.gov bills (per topic) | daily | direct |
| Open States bills | daily | Open States MCP |

### Generic ad-hoc
| Source | Cadence | Implementation |
|---|---|---|
| URL change detection (per watched URL) | per-watch | changedetection.io self-hosted |
| Product price drops (per URL) | hourly | Keepa (Amazon) or changedetection |

**v1 ships:** RSS, YouTube channels, GitHub releases, stocks, sports, weather, NWS alerts, packages, flights, URL change, EDGAR filings.
**Defer to v2:** Reddit, Mastodon, Linear/Jira/Slack, crypto, AirVisual, cheap flight watcher, concert availability, civic.

---

## 6. Layer C — Per-integration sync (fallback when no webhook)

For OAuth integrations where webhook coverage is incomplete.

| Integration | Cadence | Implementation |
|---|---|---|
| Gmail incremental | 15 min (webhook preferred) | Composio Gmail MCP |
| Calendar incremental | 15 min (webhook preferred) | Composio Calendar MCP |
| Notion page changes | hourly | Official Notion MCP |
| Health (Terra) full pull | daily + webhook | Terra direct |
| Strava activity | hourly | Strava MCP |
| Spotify recent | 30 min (low priority) | Spotify MCP |
| Readwise daily review | daily | Readwise API |

**v1 ships:** Gmail, Calendar.
**Defer to v2:** Notion, Terra, Strava, Spotify, Readwise.

---

## 7. Layer D — Webhooks

| Source | Trigger | Implementation |
|---|---|---|
| Composio (Gmail/Calendar/Notion) | content change | Composio webhook endpoint |
| TrackingMore | package status change | TrackingMore webhook |
| Terra | new sleep/recovery data | Terra webhook |
| YouTube WebSub | new channel upload | PubSubHubbub |
| Apple Shortcuts | user-pushed from iPhone | Custom webhook endpoint |
| Twilio inbound | SMS/voice incoming | Twilio webhook |
| Cal.com / Calendly | booking event | provider webhook |
| Internal: OAuth callback | integration connected | internal HTTP |

**v1 ships:** Composio (Gmail/Calendar), TrackingMore, OAuth callback, Twilio inbound (already wired for WhatsApp).
**Defer to v2:** Notion (Composio), Terra, YouTube WebSub, Apple Shortcuts, Cal.com.

---

## 8. Layer E — Reactive-only sources

Called per BRAIN turn. Never polled. Each source becomes one or more tools in the BRAIN catalog.

| Source | Tool wrapper | Implementation | Cost |
|---|---|---|---|
| Wolfram Alpha | `compute_math(question)` | Direct API | $2/1k |
| Exa | `search_web(q, freshness?)` (primary) | Exa MCP or direct | $2.5/1k, 1k free |
| Tavily | (fallback inside `search_web` client) | Direct API | 1k free |
| Foursquare Places | `find_places(query, near?, open_now?)` | Foursquare MCP | 500 free Pro/mo |
| Nutritionix | `calorie_lookup(food, qty?)` | Direct API | Free generous |
| Veryfi | `parse_receipt(image_url)` | Direct API | Paid per receipt |
| Supadata | `transcribe_video(url)` | Direct API | Paid |
| YouTube Data API v3 | (used inside `transcribe_video` for metadata) | Direct or MCP | 10k units/day free |
| TheMovieDB | `movie_lookup(title)` | Direct API | Free |
| Open Library | `book_lookup(title, author?)` | Direct API | Free |
| Translate (Google/DeepL) | `translate(text, lang)` | Direct API | Free tier |
| Finnhub (per-ticker quote) | `stock_price(symbol)` | Direct (shared client w/ poller) | Free tier |
| CoinGecko (per-coin quote) | `crypto_price(symbol)` | MCP (shared client w/ poller) | Free generous |
| GDELT (query) | `news_search(q, window?)` | direct (shared client w/ poller) | Free |
| OpenWeather (single query) | `weather_at(location, when?)` | direct (shared client w/ poller) | Free |
| Hacker News (top) | `top_hn(category?)` | MCP (shared client w/ poller) | Free |
| API-Sports (single query) | `score_of(team)` | MCP (shared client w/ poller) | Free / $19 |

**v1 ships:** Wolfram, Exa, Foursquare, Nutritionix, Veryfi, Open Library, Finnhub, GDELT, OpenWeather, HN, Translate.
**Defer to v2:** Supadata (transcripts), TheMovieDB, CoinGecko reactive (poller exists), API-Sports.

---

## 9. MCP vs direct API — decision rules

For each source, choose:

```
Has a high-quality MCP server already?
  → Use it. Same wrapper serves both pollers and reactive tools.
  Examples: GDELT, HN, news aggregators, Foursquare, GitHub, Notion, Linear.

Donna-specific magic where wrapping value is in our code?
  → Hand-craft direct API client.
  Examples: TrackingMore, Veryfi, Wolfram, Nutritionix, Supadata.

OAuth integration?
  → Composio MCP gateway (Gmail/Calendar/Notion).
  Single auth surface, refresh-token management, mode/exclusion enforcement
  layer on top.

Push-capable source?
  → Always prefer webhook over polling. Polling is fallback only.
  Examples: Gmail (Composio webhook), TrackingMore (webhook), Terra (webhook).

Subscription/notification via MCP?
  → Spec exists, adoption near-zero (Claude Desktop doesn't support, March 2026).
  Don't rely on it. Treat MCP as reactive-only; ambient = our pollers.
```

---

## 10. Workers

```
src/donna/workers/
  poll_worker.ts            # cadence-driven, runs Layer A + Layer B pollers
  watch_worker.ts           # evaluates per-user watches, fires when conditions met
  integration_sync.ts       # Layer C — incremental sync for OAuth integrations
  proactive_dispatcher.ts   # drains proactive_events, scores, may invoke BRAIN
  schedule_worker.ts        # fires due rows in scheduled_jobs (reminders, recurring)
```

Each runs as a separate process (Railway service). No shared memory. Coordinate via Postgres.

### Cadence reference

```
10s     proactive_dispatcher tick (drain proactive_events queue)
10s     schedule_worker tick (fire due scheduled_jobs)

5min    stock + crypto + sports watches (during active windows)

15min   HN poll
15min   gmail incremental (fallback if webhook delayed)
15min   gcal incremental (fallback if webhook delayed)

30min   GDELT poll
30min   user RSS poll
30min   YouTube RSS poll (per subscribed channel)
30min   flight tracking (during active travel)
30min   spotify recent (low priority)

hourly  weather forecast (per location)
hourly  Notion page changes
hourly  Strava
hourly  url-change watches (changedetection.io managed)

10 min  NWS severe alerts (in active zones, US)

4hr     package tracking (exponential backoff toward delivery)

daily   arXiv per category
daily   GitHub trending
daily   Health (Terra) full sync
daily   Readwise daily review
daily   SEC EDGAR filings
daily   Federal Reserve / Treasury releases
daily   congress.gov bills
daily   cheap flight watcher
```

---

## 11. Storage (just for ingestion)

Tables that this PRD owns. Other tables (memory, observations, etc.) are out of scope.

```sql
raw_items(
  id, user_id?,             -- null for shared-substrate items pre-fanout
  source text,              -- 'gdelt' | 'hn' | 'rss' | 'finnhub' | 'youtube_rss' | ...
  source_ref text,          -- url | message_id | tracking_no | etc.
  title text,
  content text,
  url text?,
  meta jsonb,               -- source-specific fields
  fetched_at timestamptz
)

dedup_ledger(
  user_id, ref_hash, seen_at
  -- 7-day TTL, prevents re-surfacing same item
)

proactive_events(
  id, user_id, source, source_ref,
  score real,                       -- pre-score from deterministic scorer
  signals jsonb,                    -- which user.interests/watches/loops matched
  status text,                      -- 'pending' | 'shipped' | 'dropped' | 'held' | 'escalated'
  payload jsonb                     -- enough context for BRAIN if it fires
)

watches(
  id, user_id, kind, ref jsonb, state jsonb, status,
  cadence_seconds, last_polled_at, last_fired_at
  -- kind: 'stock_alert' | 'package' | 'flight' | 'youtube_channel' | 'url_change' | ...
)

feeds(
  user_id, kind, ref text, label text, active bool, added_at
  -- user-managed: rss urls, youtube channel ids, reddit subs, github repos
)
```

---

## 12. Pipeline detail

### 12.1 Polling flow

```
poll_worker tick → for each source × user (or just source for Layer A):
  → call client.fetch()
  → for each new item:
      → check dedup_ledger; skip if seen
      → write to raw_items
      → write to dedup_ledger
      → run pre-scorer against user.interests, watches, loops
      → if score > threshold: write to proactive_events
      → mirror to Supermemory for future recall (regardless of surfacing)
```

### 12.2 Watch evaluation flow

```
watch_worker tick → for each active watch where last_polled_at is due:
  → call source-specific evaluator (e.g., finnhub.price for stock_alert)
  → compare against watch.state
  → if condition met:
      → write to proactive_events with high score
      → update watch.last_fired_at
      → optionally update watch.state (for "next threshold" semantics)
```

### 12.3 Webhook flow

```
incoming HTTP → handler validates signature
  → normalize payload to RawItem shape
  → write to raw_items
  → run pre-scorer
  → write to proactive_events if scored
```

### 12.4 Dispatcher flow

```
proactive_dispatcher tick → drain proactive_events WHERE status='pending':
  → check rate_limit (quota, cooldown, quiet hours, active-chat suppression)
     → if blocked: status='dropped', record suppressed_reason
  → call Haiku judge with payload + user_state
     → judge returns {action: ship|drop|hold|escalate, draft, register, needs_tools}
  → ship: voice_validator → ship_draft → WhatsApp + ChatMessage + ProactivePing → status='shipped'
  → drop: status='dropped'
  → hold: insert PendingProactiveNote (12h TTL) → status='held'
  → escalate: invoke BRAIN(proactive) with payload as trigger context
              → BRAIN may use any tools, may send_burst or stay silent
              → status='escalated' or 'shipped'
```

### 12.5 Reactive flow (no pipeline)

BRAIN calls a Layer E tool directly. No queue, no scorer, no dispatcher. Tool handler validates input → calls client → returns result. <1s latency.

---

## 13. Cost model (per active user/day)

```
A — World substrate (mostly free, GDELT/HN/RSS/Fed all $0)        ~$0.005
B — User watches (5 active stocks × 5min market polls,
    1 package, 1 flight when active, 3 YouTube channels)            ~$0.020
C — Integration sync (Gmail incremental, gcal incremental
    via Composio)                                                    ~$0.010
D — Webhooks                                                         ~$0.000

E — Reactive (per turn ~3 tool calls, 5 reactive turns/day):
    Exa (5 queries × $0.0025)                                       ~$0.0125
    Wolfram (2 queries × $0.002)                                    ~$0.004
    Foursquare (1-2 calls × free tier)                              ~$0.000
    Nutritionix (3 lookups × free)                                  ~$0.000
    Veryfi (1 receipt × $0.05)                                      ~$0.050
    other reactive utilities                                        ~$0.005

Pipeline:
    Pre-scorer (deterministic)                                       free
    Haiku judge (~10 calls/day surviving pre-score × $0.0003)       ~$0.003
    BRAIN(proactive) ships (~3/day × $0.02)                         ~$0.060
    BRAIN(reactive) (~5 turns/day × $0.03)                          ~$0.150

────────────────────────────────────────────────────────────────────────
                                                          Total: ~$0.32/day
```

Heaviest contributors: BRAIN reactive turns and Veryfi receipts. World engine layer alone is ~$0.05/user/day.

---

## 14. Phased rollout

### v1 — World engine ships these 18 sources

**Layer A (4):** GDELT, Hacker News, NewsAPI aggregator, Federal Reserve.
**Layer B (10):** RSS, YouTube channels, GitHub releases, stocks, sports, weather, NWS alerts, packages, flights, URL change.
**Layer C (2):** Gmail, Calendar (via Composio).
**Layer D (4):** Composio (Gmail/Calendar), TrackingMore, OAuth callback, Twilio inbound.
**Layer E (11):** Wolfram, Exa, Foursquare, Nutritionix, Veryfi, Open Library, Finnhub, GDELT (reactive), OpenWeather (reactive), HN (reactive), Translate.

### v2 — Add the rest

**Layer A:** Product Hunt, arXiv, Substack popular, GitHub trending.
**Layer B:** Reddit, Mastodon, Linear/Jira/Slack, crypto, AirVisual, cheap flight watcher, concerts, civic.
**Layer C:** Notion, Terra, Strava, Spotify, Readwise.
**Layer D:** Notion (Composio), Terra, YouTube WebSub, Apple Shortcuts, Cal.com.
**Layer E:** Supadata, TheMovieDB, CoinGecko (reactive), API-Sports (reactive).

---

## 15. Reliability gates (v1)

- Polling cadence holds within ±10% of target
- Webhook handlers respond <500ms p95
- Pre-scorer drops ≥85% of raw_items as noise (target hit-rate ≤15%)
- Haiku judge p95 latency <8s (existing target)
- TrackingMore + Composio webhook signature validation 100%
- No duplicate surfacing within 7-day dedup window
- Watch firing within 5 min of true threshold cross
- Integration sync: gmail/gcal incremental sync runs every 15 min without lag

Any miss emits an alert. No silent failures.

---

## 16. Open questions

1. **Composio cost vs direct OAuth.** Composio is faster to ship and centralizes refresh-token logic, but adds per-call cost and latency. v1 uses Composio; revisit at scale.

2. **MCP server quality vetting.** Many MCPs are community implementations of varying quality. Need a small vetting checklist before adopting (auth handling, error shape, rate-limit behavior, last commit recency).

3. **changedetection.io: self-hosted or cloud?** Self-hosted is free but ops overhead. Cloud is $8.99/mo. v1: cloud for speed; revisit if URL-watch volume grows.

4. **Pre-scorer thresholds.** Need empirical tuning per layer. Start at score ≥ 0.3 for Layer A items, ≥ 0.5 for derivative scoring against user interests. Ship with telemetry to tune.

5. **Dedup window.** 7 days for most items; longer for stable identifiers (tracking numbers, flight codes — until terminal state). Need per-source override.

6. **Layer A fanout to users.** Universal pollers fetch once, then score per-user against interests. Q: store one global copy in `raw_items.user_id = NULL` and scorer fans out to events, OR copy into per-user rows. Recommendation: NULL global rows, per-user `proactive_events` only.

7. **Haiku judge bypass for high-confidence specific watches.** A package marked "delivered" by TrackingMore probably doesn't need Haiku to decide whether to surface — it's a known-shape event. Allow specific watch kinds to skip the judge and ship directly with rate-limit gating only.

8. **Integration sync frequency vs Composio cost.** 15-min polling per user gets expensive if Composio bills per call. Webhook-first; polling only if webhook misses. Add metric for webhook-vs-poll hit ratio.

---

End of World Engine PRD.
