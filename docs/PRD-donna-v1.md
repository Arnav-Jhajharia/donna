# Donna — World Engine PRD

**Status:** Draft (2026-05-07)
**Scope:** The complete sense + tool surface for Donna's world engine. Every source, every tool, every wire. Defines the reactive ↔ proactive pipeline at implementation depth.
**Out of scope:** User model entities, dashboard, voice/register, onboarding, privacy UX. Those live in other docs.
**Target codebase:** `donna-prod` (TypeScript). Concepts language-neutral.

---

## 0. TL;DR

Donna's world engine is one shared **client layer** wrapping ~35 data sources, used in two consumption patterns:

- **Reactive**: BRAIN tools call clients on demand (per turn)
- **Ambient**: Workers poll clients on cadence + webhooks push events; the proactive lane scores and ships

Sources are MCP servers when a quality wrapper exists, direct APIs when wrapping value is in our code, Composio for OAuth integrations. Same client used by both paths — one integration, two consumption modes.

The **proactive pipeline** is intentionally light: most events are shipped by a Haiku judge composing from structured payload. BRAIN escalation only when composition genuinely requires tool access.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                 │
│  ─────────────────────────────────────────────────────────────────  │
│   MCP servers              │  Direct APIs            │  Composio    │
│   (community + official)   │  (Donna magic + niche)  │  (OAuth gw)  │
└──────────────────────┬─────────────────────┬──────────────┬─────────┘
                       │                     │              │
                       └─────────────────────┴──────────────┘
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │ CLIENT LAYER (one file per source)  │
                       │   normalizes + retries + fallbacks  │
                       │   shared by both paths              │
                       └────────────┬───────────────────┬────┘
                                    │                   │
                          ┌─────────┴─────┐    ┌────────┴────────┐
                          │ Pollers       │    │ Reactive tools  │
                          │ (workers)     │    │ (called by      │
                          │ + Webhook     │    │  BRAIN per turn)│
                          │ handlers      │    └────────┬────────┘
                          └────────┬──────┘             │
                                   │                    │
                                   ▼                    │
                       ┌──────────────────────┐         │
                       │ raw_items +          │         │
                       │ proactive_events     │         │
                       └──────────┬───────────┘         │
                                  │                     │
                                  ▼                     │
                       ┌──────────────────────┐         │
                       │ Pre-scorer +         │         │
                       │ Haiku judge          │         │
                       └──────────┬───────────┘         │
                                  │                     │
                       ┌──────────┴───────────┐         │
                       │                      │         │
                  ship │              escalate│         │
                  direct                      ▼         ▼
                  (no LLM after          ┌──────────────────────┐
                   judge)                │ BRAIN (Sonnet 4.6)   │
                       │                 │ ReAct loop           │
                       │                 │ uses same clients    │
                       │                 │ via tool layer       │
                       │                 └──────────┬───────────┘
                       │                            │
                       └────────────┬───────────────┘
                                    ▼
                              WhatsApp / Dashboard
```

The critical insight: **clients are the bottleneck of integration work.** Every API/MCP gets ONE client file. Workers and tools both call it. We don't write Gmail integration twice (once for the worker, once for the tool).

---

## 2. The complete source registry

Every source we'll integrate, with implementation details. Format per entry:

```
NAME (layer)
  Implementation:  MCP package OR API endpoint
  Auth:            how authed
  Rate limit:      free tier limits
  Cadence:         polling cadence (if polled) or webhook trigger
  Cost:            $ at scale
  Reactive tool:   tool name(s) wrapping this source for BRAIN
  Client file:     src/donna/clients/<file>.ts
```

Layers: **A** = world substrate (universal poll), **B** = user-specific watch, **C** = integration sync, **D** = webhook push, **E** = reactive-only.

Many sources are multi-layer (e.g., Finnhub: Layer A for market overview poll, Layer B for per-ticker watches, Layer E for `stock_price` reactive tool — all one client).

### 2.1 News & current events

```
GDELT 2.0  (Layer A + E)
  Implementation:  GDELT MCP via Apify  https://apify.com/visita/gdelt-news/api/mcp
                   OR direct: https://api.gdeltproject.org/api/v2/doc/doc
  Auth:            none (free)
  Rate limit:      generous (no documented hard cap for reasonable use)
  Cadence:         every 30 min (Layer A poll)
  Cost:            free
  Reactive tool:   news_search(query, window?, freshness?)
  Client file:     src/donna/clients/gdelt.ts
  
Hacker News  (Layer A + E)
  Implementation:  Algolia API (https://hn.algolia.com/api) — direct, free, no auth
                   Multiple community MCPs available; recommend dannylee1020/hackernews-mcp
  Auth:            none
  Rate limit:      ~1k req/hr soft
  Cadence:         every 15 min (top stories)
  Reactive tool:   top_hn(category?), hn_search(query)
  Client file:     src/donna/clients/hackernews.ts

NewsAPI Aggregator  (Layer A)
  Implementation:  Apify Nexgendata News MCP — bundles 27 outlets (Reuters, AP, BBC, CNN,
                   Bloomberg, etc.) under one MCP
                   https://apify.com/nexgendata/news-mcp-server
  Auth:            Apify API token
  Rate limit:      Apify standard (depends on plan; free tier ~$5/mo equivalent)
  Cadence:         every 30 min
  Reactive tool:   (none v1; reactive uses Exa or news_search direct)
  Client file:     src/donna/clients/newsaggregator.ts

User RSS  (Layer B)
  Implementation:  generic RSS parser (rss-parser npm) — direct
  Auth:            none
  Rate limit:      n/a (per-source dependent)
  Cadence:         every 30 min, per subscribed feed
  Reactive tool:   (none direct; entries flow to recall via Supermemory)
  Client file:     src/donna/clients/rss.ts

YouTube channel uploads  (Layer B + D)
  Implementation:  Layer B poll via channel RSS feed:
                     https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>
                   Layer D push via WebSub/PubSubHubbub:
                     https://pubsubhubbub.appspot.com/
                   Reactive metadata via YouTube Data API v3
                     https://developers.google.com/youtube/v3
  Auth:            none for RSS; API key for Data API v3
  Rate limit:      free RSS unlimited; Data API v3 = 10k units/day
  Cadence:         RSS poll every 30 min OR WebSub push instant
  Reactive tool:   (none direct; entries flow into raw_items + recall)
                   transcribe_video uses Supadata, separate
  Client file:     src/donna/clients/youtube.ts

Reddit subreddit feeds  (Layer B)
  Implementation:  Reddit JSON endpoint  https://reddit.com/r/<sub>/new.json
                   Multiple community MCPs available
  Auth:            none for read-only; OAuth for write
  Rate limit:      60 req/min unauthenticated
  Cadence:         every 30 min per subscribed sub
  Reactive tool:   (none v1)
  Client file:     src/donna/clients/reddit.ts

Federal Reserve / Treasury  (Layer A)
  Implementation:  FRED API  https://fred.stlouisfed.org/docs/api/fred/
  Auth:            FRED API key (free)
  Rate limit:      120 req/min
  Cadence:         daily
  Reactive tool:   economic_indicator(series_id)
  Client file:     src/donna/clients/fred.ts

arXiv  (Layer A)
  Implementation:  arXiv RSS  http://export.arxiv.org/rss/<category>
                   OR API  http://export.arxiv.org/api/query
  Auth:            none
  Rate limit:      1 req per 3 sec
  Cadence:         daily, per subscribed category
  Reactive tool:   (none v1)
  Client file:     src/donna/clients/arxiv.ts

Substack popular  (Layer A)
  Implementation:  generic RSS via author URLs (uses rss client)
  Auth:            none
  Cadence:         hourly, per author followed
  Reactive tool:   (none v1)
  Client file:     reuses src/donna/clients/rss.ts
```

### 2.2 Markets & finance

```
Finnhub  (Layer A + B + E)
  Implementation:  direct https://finnhub.io/api/v1
  Auth:            API key (free tier)
  Rate limit:      60 req/min on free tier
  Cadence:         Layer B: 5 min during market (per watched ticker)
                   Layer A: market summary every 30 min
  Reactive tool:   stock_price(symbol), stock_news(symbol)
  Client file:     src/donna/clients/finnhub.ts

CoinGecko  (Layer A + B + E)
  Implementation:  CoinGecko MCP  https://github.com/coingecko/coingecko-mcp (community)
                   OR direct https://www.coingecko.com/api/documentation
  Auth:            optional Demo API key for higher limits
  Rate limit:      30 req/min free, 500 req/min Demo
  Cadence:         Layer B: 5 min per watched coin
  Reactive tool:   crypto_price(symbol), crypto_marketcap(symbol)
  Client file:     src/donna/clients/coingecko.ts

SEC EDGAR  (Layer B)
  Implementation:  direct https://data.sec.gov/submissions/CIK<10-digit>.json
                   No MCP needed; well-documented JSON
  Auth:            none, but User-Agent header required identifying contact
  Rate limit:      10 req/sec
  Cadence:         daily, per watched company CIK
  Reactive tool:   sec_filings(ticker_or_cik, kind?)
  Client file:     src/donna/clients/edgar.ts

Alpaca (alternative to Finnhub for trading-grade data)  (Layer E only at v1)
  Implementation:  Alpaca official MCP  https://github.com/alpacahq/alpaca-mcp-server
  Auth:            Alpaca API key + secret
  Rate limit:      generous on Pro
  Cost:            free for paper trading; live trading subscription
  Reactive tool:   (defer; Finnhub covers v1 needs)
  Client file:     deferred
```

### 2.3 Sports

```
API-Sports  (Layer B + E)
  Implementation:  direct https://api-sports.io
                   Multiple community MCPs available
  Auth:            API key
  Rate limit:      100 req/day free; 7,500 req/day at $19/mo
  Cadence:         Layer B: 5 min during game windows (per followed team)
  Reactive tool:   score_of(team), game_status(team_or_match)
  Client file:     src/donna/clients/apisports.ts

Football-Data.org (soccer specifically)  (Layer B)
  Implementation:  direct https://www.football-data.org/documentation
  Auth:            free API key
  Rate limit:      10 req/min on free; 12 major leagues permanently free
  Cadence:         5 min during games
  Reactive tool:   (subset of score_of, routed by sport detection)
  Client file:     src/donna/clients/footballdata.ts

TheSportsDB (free fallback)  (Layer E)
  Implementation:  https://www.thesportsdb.com/free_sports_api
  Auth:            none
  Cost:            free
  Reactive tool:   (fallback inside score_of)
  Client file:     src/donna/clients/thesportsdb.ts
```

### 2.4 Weather & environment

```
OpenWeather  (Layer B + E)
  Implementation:  direct https://openweathermap.org/api
                   Reference MCP exists in modelcontextprotocol/servers
  Auth:            API key
  Rate limit:      60 calls/min, 1M calls/mo on free
  Cadence:         hourly forecast per user location
  Reactive tool:   weather_at(location, when?)
  Client file:     src/donna/clients/openweather.ts

NWS (US severe alerts)  (Layer B)
  Implementation:  direct https://www.weather.gov/documentation/services-web-api
  Auth:            none, User-Agent header
  Rate limit:      generous
  Cadence:         every 10 min for active alert zones
  Reactive tool:   weather_alerts(location)
  Client file:     src/donna/clients/nws.ts

AirVisual (air quality)  (Layer B)
  Implementation:  direct https://www.iqair.com/air-pollution-data-api
  Auth:            API key
  Rate limit:      10k calls/mo on free Community plan
  Cadence:         hourly per user city
  Reactive tool:   air_quality(location)
  Client file:     deferred (v2)
```

### 2.5 Travel & logistics (the magic-API tier)

```
TrackingMore  (Layer B + D + E)
  Implementation:  direct https://www.trackingmore.com/api
                   Webhook supported for real-time push
  Auth:            API key
  Rate limit:      50/mo free, 200/mo $9, 2k/mo $59
  Cadence:         Layer B: 4hr exponential backoff toward delivery
                   Layer D: webhook on status change (preferred)
  Reactive tool:   track_package(tracking_no, carrier?)
  Client file:     src/donna/clients/trackingmore.ts
  
AirLabs (flight tracking)  (Layer B + E)
  Implementation:  direct https://airlabs.co/docs
  Auth:            API key
  Rate limit:      1k req/mo free, 25k req/mo $49
  Cadence:         every 30 min during user's active travel window
  Reactive tool:   track_flight(flight_no, date?)
  Client file:     src/donna/clients/airlabs.ts

Alternatives:
  AviationStack — 100/mo free (too tight for ambient)
  FlightAware AeroAPI — 500/mo free personal (good fallback)
```

### 2.6 Computation & search

```
Wolfram Alpha  (Layer E)
  Implementation:  direct https://products.wolframalpha.com/api
  Auth:            App ID
  Rate limit:      2k req/mo free Simple API
  Cost:            ~$2 per 1k queries
  Reactive tool:   compute_math(question)
  Client file:     src/donna/clients/wolfram.ts

Exa (semantic search)  (Layer E + B-derived)
  Implementation:  direct https://docs.exa.ai
                   OR Exa MCP
  Auth:            API key
  Rate limit:      1k searches free, $2.5/1k after
  Cadence:         Layer B agentic queries: hourly per active topic_watch
  Reactive tool:   search_web(query, freshness?), follow_topic(query)
  Client file:     src/donna/clients/exa.ts

Tavily (general agentic search, fallback)  (Layer E)
  Implementation:  direct https://tavily.com
  Auth:            API key
  Rate limit:      1k searches/mo free, $8/1k after
  Reactive tool:   (fallback inside search_web client)
  Client file:     src/donna/clients/tavily.ts

Brave Search / Serper (cheap raw SERP)  (Layer E)
  Implementation:  direct
  Auth:            API key
  Rate limit:      Brave $5/mo credit; Serper $1/1k cheap raw
  Reactive tool:   web_search(query)
  Client file:     src/donna/clients/serper.ts
```

### 2.7 Local data & places

```
Foursquare Places  (Layer E)
  Implementation:  Foursquare Places API direct
                   https://docs.foursquare.com/developer/reference/places-api-overview
                   Foursquare MCP exists (community)
  Auth:            API key
  Rate limit:      500 free Pro calls/mo from June 2026
  Reactive tool:   find_places(query, near?, open_now?)
  Client file:     src/donna/clients/foursquare.ts

Yelp Fusion (alternative)  (Layer E)
  Implementation:  direct https://docs.developer.yelp.com/docs/fusion-intro
  Auth:            API key
  Rate limit:      500/day free
  Reactive tool:   (fallback inside find_places)
  Client file:     src/donna/clients/yelp.ts
```

### 2.8 Food & receipts

```
Nutritionix  (Layer E)
  Implementation:  direct https://www.nutritionix.com/business/api
  Auth:            App ID + key
  Rate limit:      free tier ~200 req/day, paid above
  Reactive tool:   calorie_lookup(food, qty?), nutrition_breakdown(meal_text)
  Client file:     src/donna/clients/nutritionix.ts

Veryfi (receipt OCR)  (Layer E)
  Implementation:  direct https://www.veryfi.com/api/
  Auth:            API key + Client ID
  Rate limit:      paid per receipt
  Cost:            ~$0.05/receipt
  Reactive tool:   parse_receipt(image_url)
  Client file:     src/donna/clients/veryfi.ts
```

### 2.9 Video & transcripts

```
Supadata (YouTube transcripts)  (Layer E)
  Implementation:  direct https://supadata.ai/youtube-transcript-api
  Auth:            API key
  Rate limit:      paid
  Reactive tool:   transcribe_video(url)
  Client file:     src/donna/clients/supadata.ts
  Notes:           AI fallback when YouTube has no captions — key differentiator
```

### 2.10 Books & movies

```
Open Library  (Layer E)
  Implementation:  direct https://openlibrary.org/developers/api
  Auth:            none
  Rate limit:      generous
  Reactive tool:   book_lookup(title, author?), capture_book(title) helper uses this
  Client file:     src/donna/clients/openlibrary.ts

TheMovieDB  (Layer E)
  Implementation:  direct https://developer.themoviedb.org/reference
  Auth:            API key
  Rate limit:      ~50 req/sec
  Reactive tool:   movie_lookup(title), find_movie_for(...)
  Client file:     src/donna/clients/tmdb.ts
```

### 2.11 Reading & culture (deferred to v2)

```
Readwise  (Layer C, v2)
  Implementation:  direct https://readwise.io/api_deets
  Auth:            user OAuth token
  Reactive tool:   readwise.recent_highlights()
  Client file:     deferred

Spotify  (Layer C, v2)
  Implementation:  Spotify MCP (community) or direct https://developer.spotify.com
  Auth:            user OAuth via Composio
  Reactive tool:   spotify.recent()
  Client file:     deferred

Strava  (Layer C, v2)
  Implementation:  Strava MCP (community) or direct https://developers.strava.com
  Auth:            user OAuth
  Reactive tool:   strava.recent()
  Client file:     deferred
```

### 2.12 Productivity & integrations (Composio gateway)

```
Gmail  (Layer C + D)
  Implementation:  Composio Gmail MCP  https://composio.dev
  Auth:            user OAuth via Composio gateway
  Cadence:         webhook real-time + 15 min poll fallback
  Reactive tool:   gmail.search(query), gmail.draft(thread_id, body), gmail.send(...)
  Client file:     src/donna/clients/gmail.ts (wraps Composio call)
  Notes:           Mode + exclusion enforcement applied here, NOT in tool layer.
                   IntegrationService applies user.mode (search_only / smart_index / full)
                   and user.exclusions (label/sender/subject regex) before returning.

Google Calendar  (Layer C + D)
  Implementation:  Composio Calendar MCP
  Auth:            user OAuth via Composio
  Cadence:         webhook real-time + 15 min poll fallback
  Reactive tool:   gcal.list(range), gcal.create(event), gcal.update(event_id, changes)
  Client file:     src/donna/clients/gcal.ts

Notion  (Layer C + D, v2)
  Implementation:  Composio Notion MCP OR official Notion MCP
  Auth:            user OAuth
  Cadence:         hourly poll + webhook
  Reactive tool:   notion.append(page, content), notion.search(query)
  Client file:     deferred

Health (Terra — unifies wearables)  (Layer C + D, v2)
  Implementation:  Terra direct https://tryterra.co
  Auth:            Terra orchestrates per-wearable OAuth (Whoop/Oura/Strava/Apple/Garmin/Fitbit)
  Cadence:         daily full pull + webhook for new data
  Reactive tool:   health.metric(metric, range?)
  Client file:     deferred
```

### 2.13 URL change watching

```
changedetection.io  (Layer B + E)
  Implementation:  direct https://changedetection.io/docs/api_v1/index.html
                   Self-hosted free; cloud $8.99/mo
  Auth:            API key
  Cadence:         per-watch configured externally
  Reactive tool:   watch_url(url, change_kind?), get_watched_changes()
  Client file:     src/donna/clients/changedetection.ts
  Notes:           Has JSONPath + jq filtering — handles much of the long tail
                   of "watch this thing" without per-domain code.
```

### 2.14 GitHub & developer

```
GitHub releases (per repo)  (Layer B)
  Implementation:  Official GitHub MCP  https://github.com/modelcontextprotocol/servers/tree/main/src/github
                   OR direct https://api.github.com
  Auth:            Personal access token (or fine-grained)
  Rate limit:      5k req/hr authenticated
  Cadence:         daily
  Reactive tool:   gh_releases(repo), gh_search(query)
  Client file:     src/donna/clients/github.ts

GitHub mentions of user  (Layer B)
  Implementation:  same client, GitHub Notifications API
  Cadence:         hourly
  Reactive tool:   (none direct; flows to proactive)

GitHub trending  (Layer A, v2)
  Implementation:  scrapes GitHub trending page (no official API)
                   OR community MCP
```

### 2.15 Civic data

```
congress.gov (federal)  (Layer B)
  Implementation:  direct https://api.congress.gov
  Auth:            API key (free)
  Rate limit:      5k req/hr
  Cadence:         daily per topic watched
  Reactive tool:   bill_status(bill_id), bills_for_topic(topic)
  Client file:     src/donna/clients/congress.ts

Open States (state legislatures)  (Layer B)
  Implementation:  Open States MCP exists; OR direct https://docs.openstates.org
  Auth:            API key
  Rate limit:      generous on free
  Cadence:         daily
  Client file:     src/donna/clients/openstates.ts
```

### 2.16 Translation

```
Google Translate / DeepL  (Layer E)
  Implementation:  direct (DeepL preferred for quality)
  Auth:            API key
  Rate limit:      DeepL free 500k chars/mo
  Reactive tool:   translate(text, lang)
  Client file:     src/donna/clients/translate.ts
```

### 2.17 Voice/SMS substrate

```
Twilio  (Layer D)
  Implementation:  Twilio SDK direct
  Auth:            Account SID + Auth token
  Cost:            SMS $0.0083/msg, Voice $0.014/min, WhatsApp via Conversations API
  Cadence:         webhook for inbound SMS/voice/WhatsApp
  Reactive tool:   (used by delivery layer, not BRAIN-callable directly)
  Client file:     src/donna/clients/twilio.ts (already in donna-prod)
```

---

## 3. Tool catalog mapped to clients

Every reactive tool has a 1-to-many mapping to clients. Most tools wrap one client with normalization; a few wrap a fallback chain.

```
Reactive tool                  → Client(s)                           Tool file
───────────────────────────────────────────────────────────────────────────
ALWAYS LOADED
  send                         (delivery layer, not source-backed)   tools/core/send.ts
  ask                          (delivery layer)                      tools/core/ask.ts
  ack                          (delivery layer)                      tools/core/ack.ts
  recall                       memory/supermemory + memory/postgres  tools/core/recall.ts
  remember                     memory/supermemory                    tools/core/remember.ts
  note                         memory/supermemory + observations     tools/core/note.ts
  get_user_state               memory/postgres (living_profile)      tools/core/get_user_state.ts
  search_web                   exa (primary) → tavily (fallback)     tools/core/search_web.ts
  web_search                   serper (cheapest raw SERP)            tools/core/web_search.ts
  schedule_check               db (scheduled_jobs)                   tools/core/schedule_check.ts
  generic_watch                db (watches)                          tools/core/generic_watch.ts
  remind                       db (scheduled_jobs)                   tools/core/remind.ts
  remind_recurring             db (scheduled_jobs)                   tools/core/remind_recurring.ts
  tool_search                  in-process registry index             tools/core/tool_search.ts
  cancel                       db (scheduled_jobs / watches)         tools/core/cancel.ts

DEFERRED — Logs (10)
  log_expense, log_calories,   db (per-table)                        tools/logs/*.ts
  log_workout, log_sleep,      log_calories also calls nutritionix
  log_mood, log_energy,
  log_water, log_substance,
  log_weight, log_med

DEFERRED — Captures (5)
  capture_link                 web fetch + supermemory               tools/captures/capture_link.ts
  capture_quote                supermemory                           tools/captures/capture_quote.ts
  capture_idea                 supermemory                           tools/captures/capture_idea.ts
  capture_recipe               web fetch + supermemory               tools/captures/capture_recipe.ts
  capture_book                 openlibrary + supermemory             tools/captures/capture_book.ts

DEFERRED — People (10)
  person_*, draft_message_to,  db (people, person_attributes,        tools/people/*.ts
  schedule_with, prep_for_*    person_meetings) + memory + gcal/gmail

DEFERRED — Loops (4)
  loop_open/close/list/aging   db (loops)                            tools/loops/*.ts

DEFERRED — Prefs/Goals (5)
  pref_*, goal_*               db (preferences, goals)               tools/prefs_goals/*.ts

DEFERRED — Reflection (8)
  reflect, summarize_day,      memory + db aggregations              tools/reflect/*.ts
  weekly_review (workflow tool: combines gmail.search + recall + 
                  llm summary + notion.append in one call)
  get_pattern, get_aggregate   db
  relationship_check_in        db (people, person_meetings, loops)

DEFERRED — Health workflows (4) [v2]
  recovery_check_today         terra (health)
  training_load                terra
  correlate_sleep_mood         db (sleep_log + mood_log)
  nutrition_breakdown          nutritionix

DEFERRED — Finance workflows (3)
  spend_check                  db (expenses)
  recurring_charges_review     db
  budget_status                db

DEFERRED — Writing (4)
  draft_email_in_voice         memory + LLM compose                  tools/writing/*.ts
  draft_message_in_voice       memory + LLM compose
  edit_for_brevity             LLM compose
  summarize_thread             gmail + LLM compose

DEFERRED — Discovery (4)
  find_restaurant_for          foursquare + (yelp fallback)
  find_book_like               openlibrary + supermemory
  find_movie_for               tmdb
  find_recipe_for              web search + LLM compose

DEFERRED — Magic verbs (16)
  track_package                trackingmore                          tools/magic/track_package.ts
  track_flight                 airlabs                               tools/magic/track_flight.ts
  set_price_alert              db (watches) + finnhub on poll        tools/magic/set_price_alert.ts
  poll_score                   apisports / footballdata              tools/magic/poll_score.ts
  follow_topic                 db (watches) + exa on poll            tools/magic/follow_topic.ts
  watch_repo_release           db (watches) + github on poll
  watch_artist_release         db (watches) + spotify on poll [v2]
  watch_substack               db (watches) + rss on poll
  watch_youtube_channel        db (watches) + youtube on poll
  watch_price_drop             db (watches) + changedetection
  watch_concert                db (watches) + ticketmaster [v2]
  watch_cheap_flight           db (watches) + skyscanner [v2]
  find_places                  foursquare → yelp fallback
  compute_math                 wolfram
  parse_receipt                veryfi
  transcribe_video             supadata + youtube
  watch_url                    db (watches) + changedetection

DEFERRED — Single-call utilities (8)
  stock_price                  finnhub                               tools/magic/stock_price.ts
  crypto_price                 coingecko
  news_search                  gdelt
  weather_at                   openweather
  top_hn                       hackernews
  score_of                     apisports → thesportsdb fallback
  translate                    deepl → google fallback
  research_topic               exa + LLM compose

DEFERRED — Integration management (9)
  integration.connect/...      composio + db (integrations)          tools/integrations/management/*.ts
  route.set/get/list           db (routes)

DEFERRED — Integration use (12)
  gmail.search/draft/send      gmail (Composio-wrapped)              tools/integrations/use/gmail.ts
  gcal.list/create/update      gcal (Composio-wrapped)
  notion.append/search [v2]    notion
  spotify.recent [v2]          spotify
  readwise.recent_highlights [v2] readwise
  health.metric [v2]           terra
  strava.recent [v2]           strava
```

**Total: ~120 tools, ~35 client files. Roughly 4:1 tool:client ratio because workflow tools combine multiple clients.**

---

## 4. Pipeline logic — reactive vs proactive

### 4.1 Reactive turn (BRAIN with full tool palette)

```
1. User sends WhatsApp message
2. Twilio webhook → ingress/whatsapp.ts → write to chat_messages
3. brain.ts.donna_turn(mode="reactive") starts:
   - Loads system prompt + voice rules
   - Loads always-loaded tool schemas (~15)
   - Loads user_state from memory/postgres
   - Calls Anthropic SDK with messages + tools
4. BRAIN reasons, calls tools as needed
   - For unfamiliar domains: tool_search(...) → returns candidate tool names
   - tool's schema added to next turn's tool list
   - tool.handler(args, ctx) runs:
       - validates schema
       - calls one or more clients (clients/*.ts)
       - clients hit MCP servers OR direct APIs OR Composio
       - normalizes response
       - writes audit, captures observations as side effects
       - returns { data, observations?, followups? }
5. BRAIN sees result, decides next step (more tools or final send)
6. send(text) → delivery/whatsapp.ts → Twilio outbound
```

Latency budget per reactive turn: <3s p95. Most turns are 1-3 tool calls.

### 4.2 Proactive turn (cheap path, default)

This is the "simple proactive" path — most events go this way, NO BRAIN call.

```
1. Event source produces a fact:
   - poll_worker tick reads from a client → finds new item → writes raw_items + scores
   - watch_worker tick checks a watch → condition met → writes proactive_events
   - webhook handler receives push → normalizes → writes proactive_events
2. proactive_dispatcher tick (every 10s) drains proactive_events:
   - rate_limit check (quota, cooldown, quiet hours, active-chat) → may drop
   - Haiku judge call (~$0.0003):
       - input: payload + small user_state slice + voice rules
       - output: { action: ship | drop | hold | escalate, draft, register, needs_tools }
   - if action=ship and needs_tools=false:
       - voice_validator.check(draft) → passes (or reauthor once via Haiku)
       - delivery/whatsapp.ts → Twilio outbound
       - write ChatMessage (is_proactive=true) + ProactivePing
       - status='shipped'
   - if action=drop: status='dropped' with suppressed_reason
   - if action=hold: insert PendingProactiveNote (12h TTL); status='held'
   - if action=escalate or needs_tools=true: GO TO 4.3
```

Total LLM cost on this path: ~$0.0003 per event. Most events. Latency <3s.

### 4.3 Proactive turn (escalation path, rare)

When the judge says it needs tools — open-ended schedule_check, complex composition, gmail content scoring, etc.

```
3. dispatcher invokes brain.ts.donna_turn(
     mode="proactive",
     trigger=payload,
     stateless_session=true
   )
4. BRAIN(proactive) starts with:
   - same tool palette as reactive (full ~120 tools)
   - trigger payload as conversation seed
   - living_profile snippet
   - last few messages from user (read-only context, doesn't poison reactive history)
5. BRAIN reasons, calls tools (using the SAME clients reactive tools use)
6. BRAIN either:
   - calls send() with composed message → ships
   - returns silent → status='dropped'
   - calls cancel() to stop a recurring schedule → no message but state changes
   - calls schedule_check() to defer → reschedule and silent
```

Total LLM cost: ~$0.04-0.06 per fire (Sonnet with 2-5 tool calls).

### 4.4 When to escalate vs ship direct (rules of thumb)

```
ALWAYS ship direct (judge composes from payload):
  - Specific watch hits with structured payload:
    set_price_alert, track_package, track_flight, poll_score, weather_alerts,
    package status changes, flight delays, score updates
  - Reminders firing
  - Topic match where article snippet is sufficient
  - Recurring schedules with known shape (morning brief, weekly review)

ALWAYS escalate (BRAIN needed):
  - schedule_check fires (open-ended description by definition)
  - Email arrived (needs scoring against full state + threads)
  - Cross-referenced events (e.g., GDELT hit + open loop with same person)
  - Anything where judge.needs_tools=true based on payload analysis

Default: ship direct. Escalation is the exception, not the rule.
```

Target ratio: ~80% ship-direct, ~20% escalate. Will tune empirically.

### 4.5 Shared client layer

The point that makes this all efficient: reactive tools and pollers use the SAME client functions.

```ts
// src/donna/clients/finnhub.ts
export const finnhub = {
  async price(symbol: string): Promise<{ current: number, prev: number, ts: Date }> {
    // hits Finnhub /quote endpoint, normalizes
  },
  async news(symbol: string, since?: Date): Promise<NewsItem[]> {
    // hits Finnhub /company-news endpoint
  },
};
```

```ts
// reactive tool wrapping finnhub
// src/donna/tools/magic/stock_price.ts
export const stockPrice = defineTool({
  name: "stock_price",
  description: "...",
  schema: z.object({ symbol: z.string() }),
  handler: async ({ symbol }, ctx) => {
    return { data: await finnhub.price(symbol) };
  },
  loaded: "deferred",
});
```

```ts
// poller using same client
// src/donna/workers/watch_worker.ts (excerpt)
async function evaluateStockAlert(watch: Watch) {
  const price = await finnhub.price(watch.ref.symbol);  // SAME client function
  if (crossedThreshold(watch, price)) {
    await writeProactiveEvent(...);
  }
}
```

One Finnhub integration, two consumption modes. We never write the same auth+retry+normalization twice.

---

## 5. Workers (the ambient layer)

Five worker processes. Each runs as its own Railway service. No shared memory.

```
src/donna/workers/
  schedule_worker.ts        # fires due rows in scheduled_jobs (reminders, recurring, schedule_check)
  poll_worker.ts            # cadence-driven, runs Layer A pollers + scans Layer B watches due
  watch_worker.ts           # evaluates per-user watches (could merge with poll_worker;
                            # split for v1 clarity)
  integration_sync.ts       # Layer C — incremental sync for OAuth integrations (Composio fallback)
  proactive_dispatcher.ts   # drains proactive_events, runs scorer + judge, may invoke BRAIN
```

### Cadence reference

```
WORKER TICK CADENCES
  schedule_worker            10s
  proactive_dispatcher       10s
  watch_worker               varies per watch (5min - 4hr - daily)
  poll_worker                varies per source
  integration_sync           15min

WATCH-LEVEL CADENCES (per kind)
  stock_alert                5min during market hours, paused otherwise
  crypto_alert               5min
  poll_score                 5min during game windows
  package                    4hr exponential backoff, 1hr near delivery, webhook-driven
  flight                     30min during travel window
  url_change                 per-watch as configured in changedetection.io
  follow_topic               30min (GDELT) + hourly (Exa agentic)
  watch_youtube              30min via RSS
  watch_repo_release         daily

LAYER A POLL CADENCES
  GDELT                      30min
  Hacker News                15min
  NewsAPI aggregator         30min
  Substack popular           hourly
  Federal Reserve / FRED     daily
  arXiv (per category)       daily
  Product Hunt [v2]          daily
  GitHub trending [v2]       daily

INTEGRATION SYNC CADENCES (when no webhook)
  Gmail                      15min
  Calendar                   15min
  Notion [v2]                hourly
  Strava [v2]                hourly
  Spotify [v2]               30min
  Health (Terra) [v2]        daily

WEBHOOK ENDPOINTS (push, no poll cadence)
  Composio Gmail             real-time
  Composio Calendar          real-time
  Composio Notion [v2]       real-time
  TrackingMore               real-time on status change
  Terra [v2]                 real-time on data sync
  YouTube WebSub             real-time on upload
  Apple Shortcuts            user-pushed
  Twilio inbound             real-time (already wired)
  OAuth callback             on integration connect
```

---

## 6. Storage (ingestion-side)

Tables this PRD owns. Other tables live in the user-model PRD.

```sql
raw_items(
  id          uuid pk,
  user_id     uuid?,           -- null for shared Layer A items pre-fanout
  source      text,            -- 'gdelt' | 'hn' | 'rss' | 'finnhub' | 'youtube_rss' | ...
  source_ref  text,            -- url | message_id | tracking_no | composite key
  title       text,
  content     text,
  url         text?,
  meta        jsonb,            -- source-specific fields
  fetched_at  timestamptz,
  index on (user_id, source, fetched_at)
)

dedup_ledger(
  user_id     uuid,
  ref_hash    text,             -- sha256 of normalized source_ref
  seen_at     timestamptz,
  primary key (user_id, ref_hash)
  -- 7-day TTL purge job
)

proactive_events(
  id          uuid pk,
  user_id     uuid,
  source      text,             -- 'stock_alert' | 'topic_match' | 'package' | 'gmail' | ...
  source_ref  text,             -- watch_id, raw_item_id, message_id, etc.
  score       real,
  signals     jsonb,             -- {watch_match, trusted_source, recency_boost, ...}
  status      text,              -- 'pending' | 'shipped' | 'dropped' | 'held' | 'escalated'
  payload     jsonb,             -- enough context for judge / BRAIN
  topic_key   text,              -- for per-topic cooldown (e.g., 'stock:NVDA')
  created_at  timestamptz,
  resolved_at timestamptz?
)

watches(
  id              uuid pk,
  user_id         uuid,
  kind            text,           -- 'stock_alert' | 'package' | 'flight' | 'topic' | ...
  ref             jsonb,           -- {symbol, op, value} or {tracking_no, carrier} etc.
  state           jsonb,           -- {last_price, last_status, last_seen_ids}
  status          text,            -- 'active' | 'paused' | 'completed' | 'cancelled'
  cadence_seconds int,
  last_polled_at  timestamptz?,
  last_fired_at   timestamptz?,
  created_at      timestamptz,
  expires_at      timestamptz?
)

feeds(
  user_id     uuid,
  kind        text,                -- 'rss' | 'youtube_channel' | 'reddit_sub' | 'github_repo' | 'substack_author'
  ref         text,                -- url | channel_id | sub_name | repo_full_name
  label       text,
  active      bool,
  added_at    timestamptz,
  primary key (user_id, kind, ref)
)

scheduled_jobs(
  id          uuid pk,
  user_id     uuid,
  kind        text,                -- 'remind' | 'recurring' | 'check'
  trigger     jsonb,               -- {type: 'once'|'cron'|'recurring_until', ...}
  what        text,                -- natural-language description, used by BRAIN(proactive)
  status      text,                -- 'active' | 'paused' | 'done' | 'cancelled'
  route_ref   text?,               -- optional capability route
  created_at  timestamptz,
  fire_at     timestamptz?,
  last_run_at timestamptz?,
  next_run_at timestamptz?
)

proactive_pings(
  id              uuid pk,
  user_id         uuid,
  topic_key       text,
  source          text,
  fired_at        timestamptz,
  suppressed_reason text?
)

integrations(
  user_id              uuid,
  provider             text,
  status               text,
  mode                 text,
  config               jsonb,
  composio_account_id  text?,
  last_sync_at         timestamptz?,
  last_error           jsonb?,
  connected_at         timestamptz,
  primary key (user_id, provider)
)
```

---

## 7. Cost model

Per active user/day, fully wired:

```
SOURCE COSTS
  Layer A pollers (free for everyone)                    ~$0.005
  Layer B user watches:
    stocks (5 tickers × 78 ticks/day Finnhub free)        $0.000
    1 active package × 6 polls (TrackingMore $9/200)      $0.045/mo = ~$0.0015/day
    flights when traveling                                 free tier
    YouTube channels (3 × 48 RSS pulls/day, free)         $0.000
    URL change watches (changedetection cloud)             $8.99/mo / 30 = $0.30/day  *
    sports (game day)                                      $19/mo / 30 = $0.63/day  **
  Layer C integration syncs (Composio)                    ~$0.005
  Layer D webhooks                                         $0.000

  * URL watches usually shared across users in self-hosted mode → ~free
  ** Sports is amortized per active sports user; not per-user per-day if no team followed

REACTIVE TOOL CALLS (~5 turns/day × 3 tool calls)
  Exa (~5 queries × $0.0025)                              $0.0125
  Wolfram (~2 × $0.002)                                    $0.004
  Foursquare (~2 × free tier)                              $0.000
  Nutritionix (~3 × free)                                  $0.000
  Veryfi (~1 receipt × $0.05)                              $0.050
  GDELT/HN/Finnhub/Weather reactive                        $0.000
  Other reactive utilities                                  $0.005

LLM COSTS
  Pre-scorer (deterministic)                                free
  Haiku judge (~5 surviving events × $0.0003)              $0.0015
  BRAIN(proactive) ships direct (~3/day, judge-only)        included in judge
  BRAIN(proactive) escalates (~1/day × $0.04)              $0.04
  BRAIN(reactive) (~5 turns × $0.03)                       $0.15

SUPERMEMORY (embedding + storage)
  ~50 new items/day indexed                                 $0.005

TOTAL                                                      ~$0.27/user/day
```

Heaviest contributors: BRAIN reactive turns ($0.15) + BRAIN proactive escalations ($0.04) + Veryfi receipts ($0.05).

Optimizations available later: switch BRAIN(reactive) to Haiku for non-composition turns, batch Supermemory indexing, cache Foursquare results.

---

## 8. Phased rollout

### v1 — ship these (locked)

**Layer A (4 sources):**
GDELT, Hacker News, NewsAPI aggregator (Apify), Federal Reserve.

**Layer B (10 watch kinds):**
RSS, YouTube channels, GitHub releases, stocks (set_price_alert), sports (poll_score), weather, NWS alerts, packages (track_package), flights (track_flight), URL change (watch_url + changedetection).

**Layer C (2 integrations):**
Gmail, Calendar (via Composio).

**Layer D (4 webhooks):**
Composio (Gmail/Calendar combined endpoints), TrackingMore, OAuth callback, Twilio inbound (already wired).

**Layer E (11 reactive sources):**
Wolfram, Exa (primary), Tavily (fallback), Serper, Foursquare, Nutritionix, Veryfi, Open Library, Finnhub (reactive), GDELT (reactive), OpenWeather (reactive), HN (reactive), Translate (DeepL).

**Tools (~35):**
- 15 always-loaded
- 10 personal logs
- 5 captures
- 5 reflection (reflect, summarize_day, weekly_review, get_pattern, relationship_check_in)
- 5 magic (track_package, set_price_alert, compute_math, find_places, parse_receipt)
- 5 people (person_note/recall/last_touch, prep_for_meeting, draft_message_to)
- 4 loops
- 4 integration management (connect/status/set_mode/disconnect)
- 6 integration use (gmail.search/draft/send, gcal.list/create/update)

### v2 — add post-launch

**Layer A:** Product Hunt, arXiv, Substack popular, GitHub trending.
**Layer B:** Reddit, Mastodon, Linear/Jira/Slack, crypto, AirVisual, cheap flight, concerts, civic.
**Layer C:** Notion, Terra (health), Strava, Spotify, Readwise.
**Layer D:** Notion (Composio), Terra, YouTube WebSub, Apple Shortcuts, Cal.com.
**Layer E:** Supadata (transcripts), TheMovieDB, CoinGecko reactive, API-Sports reactive.
**Tools:** Discovery (find_*), writing aids, health workflows, more captures.

---

## 9. Reliability gates (v1)

These must pass for v1 to ship:

- Polling cadence holds within ±10% of target (alert if drift)
- Webhook handlers respond <500ms p95
- Pre-scorer drops ≥85% of raw_items as noise
- Haiku judge p95 latency <8s
- TrackingMore + Composio webhook signature validation 100%
- No duplicate surfacing within 7-day dedup window
- Watch firing within 5 min of true threshold cross
- Gmail/Calendar incremental sync runs every 15 min with no lag exceeding 30 min
- No silent failures: any reminder/sync/backfill that misses SLA emits an alert
- All integration calls write to integration_audit table
- Voice validator catches 100% of uppercase/emoji/em-dash/semicolon in proactive sends

---

## 10. Open questions

1. **Composio cost vs direct OAuth.** v1 uses Composio. Revisit at scale ($X/user/month threshold).
2. **MCP server vetting checklist.** Define before adopting community MCPs: auth handling, error shape, rate-limit behavior, last commit recency.
3. **changedetection.io self-hosted vs cloud.** v1 cloud ($8.99/mo) for speed. Revisit if URL-watch volume grows.
4. **Pre-scorer thresholds.** Empirical tuning needed. Start at score ≥ 0.3 (Layer A) and ≥ 0.5 (derivative). Ship with telemetry.
5. **Dedup window.** 7 days standard; longer for stable identifiers (tracking numbers until terminal state).
6. **Layer A fanout.** NULL global rows in raw_items, per-user proactive_events only (recommended).
7. **Haiku judge bypass for high-confidence specific watches.** A package marked "delivered" probably doesn't need Haiku — known-shape event. Allow specific watch kinds to skip judge and ship directly with rate-limit gating only.
8. **Voice/SMS in v1?** Currently deferred to v2. Twilio Conversations is the substrate when ready.
9. **Embedding provider for Postgres `chat_messages.embedding`.** Voyage 3 primary, OpenAI text-embedding-3-small fallback.
10. **Integration sync frequency vs Composio cost.** 15-min polling per user gets expensive at scale. Webhook-first; polling only as fallback. Monitor webhook-vs-poll hit ratio.
11. **Should pollers and reactive tools share rate-limit budgets per source?** Probably yes — one Finnhub free-tier budget shared across both consumption modes.

---

End of World Engine PRD.
