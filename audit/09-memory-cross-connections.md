# 09 · Memory cross-connections

The brand promise is "thinking partner with persistent memory." That promise only holds if Donna can pull a coherent answer out of multiple stores at once. If each backend is a silo, she's just a chatbot with a fancy database catalog.

This is the question this audit answers. Are the 10 backends actually fused, or are they ten separate lookup tables sharing a tool surface?

## What's there

The `recall` tool is the front door ([`donna_runtime/tools.py:931-1014`](../donna_runtime/tools.py#L931)). One natural-language query, optional `purpose` escape hatch, optional `observation_type`/`period` filters. When Donna calls it without forcing a purpose, it routes to `smart_recall` which calls `run_retrieval` ([`backend/memory/retrieval/pipeline.py:16`](../backend/memory/retrieval/pipeline.py#L16)).

The pipeline is real and it does fuse:

1. **Expansion** — Haiku rewrites the query, generates 2-3 facets, sometimes a HyDE snippet ([`expansion.py:39`](../backend/memory/retrieval/expansion.py#L39)). All in one structured call, ~one Haiku turn.
2. **Fanout** — runs in parallel against five lanes ([`fanout.py:26`](../backend/memory/retrieval/fanout.py#L26)):
   - Postgres `observations` (with deterministic structured hints — period, observation_type, ilike on raw/fields/tags)
   - Postgres `open_loops` (active + ilike on content)
   - Postgres `users.living_profile.situation_brief` (only if hint matches)
   - Supermemory `search.memories` (hybrid mode, with `related_memories`)
   - Graphiti `search` against the user's FalkorDB graph
   Each lane has an 8s timeout, errors degrade to empty.
3. **Rerank** — Reciprocal Rank Fusion with K=60, merging by (retrieved_via, source) groups, structured-priority bonus from the observations lane ([`rerank.py:13`](../backend/memory/retrieval/rerank.py#L13)).
4. **Attention boost** — optional pass to lift hits that touch active attention rows ([`attention_boost.py`](../backend/memory/retrieval/attention_boost.py)).

So when Donna calls `recall("what did I tell you about my brother last month")`, she really does hit Supermemory + Graphiti + observations + open_loops in parallel, RRF-merge, return up to top_k=8. That's the cross-source fusion the brand claims.

The `purpose` modes ([`tools.py:984-1005`](../donna_runtime/tools.py#L984)) are escape hatches:
- `observations` / `tracker` → `list_observations` only (skip everything else)
- `open_loops` / `loops` → `list_open_loops` only
- `situation_brief` / `brief` → `read_situation_brief` only

These bypass the pipeline entirely. They are single-lane reads.

The `recall_episodic` and `recall_graph` tools also exist as single-lane reads ([`tools.py:113`](../donna_runtime/tools.py#L113), [`tools.py:151`](../donna_runtime/tools.py#L151)). Their tool descriptions tell Donna to prefer them when the source is obvious.

## What works

- Five lanes, parallel, with timeouts and graceful degradation. The architecture is honest. If FalkorDB is down (we just fixed prod via the internal Railway hostname per `02-timezones.md` neighborhood) the rest of the lanes still produce a result. Same for Supermemory missing key.
- Structured hints are LLM-free ([`structured_hints.py`](../backend/memory/retrieval/structured_hints.py)) — keyword tables for observation types, regex period detector, stopword-aware tokenizer. Cheap, deterministic, and wired into the rerank as a `structured_priority` bonus so a confident "spent 12 bucks today" query can outrank fuzzy episodic hits.
- The RRF merge is the right primitive. It avoids picking a winner; everyone votes by rank.
- The attention layer can boost hits — feedback path from proactive → retrieval exists ([`attention_boost.py`](../backend/memory/retrieval/attention_boost.py)).

## What's broken or missing

- **Calendar is not in the fanout.** The `recall` pipeline does not query `calendar_entries` at all. Calendar is a separate `check_calendar` / `list_calendar` tool. So when the user asks "what did I tell you about my brother last month, doesn't he have something coming up", Donna has to make two calls. Cross-source intelligence breaks at the calendar boundary.
- **Procedural rules (Postgres tier 1/2/3) are not in the fanout.** Procedural rules feed into the system prompt at assembly time but are not searchable by `recall`. There's no way for Donna to ask "what rules do I have about you" — the model can't introspect its own behavioral memory.
- **Web is also not in the fanout.** `web_search` / `agentic_web_search` / `research` are separate tools. The 10th "backend" (Web) is conceptually outside the memory union.
- **Document chunks are not in the default `recall`.** Supermemory's `search.memories` covers episodic, but `search.documents` (which returns chunks with reranking) is its own tool, `recall_document_chunks` ([`backend/memory/tools/recall_document_chunks.py`](../backend/memory/tools/recall_document_chunks.py)). So docs the user uploaded are walled off from the unified surface.
- **Bitemporal Facts (Postgres `facts` table) are not in the fanout.** The bitemporal store ([`facts/bitemporal.py`](../backend/memory/facts/bitemporal.py)) has slick "as-of" semantics but no read tool maps it into recall. It's effectively dark code from the model's perspective.
- **Living Profile is not searched, it's pre-rendered.** It lands in the system prompt via `load_and_render` ([`user_facts/rendering.py:424`](../backend/memory/user_facts/rendering.py#L424)). Strictly correct per CLAUDE.md (do not auto-reload mid-turn) but it means a stale profile is invisible to recall — the model has to know to call `update_living_profile` if something is wrong.
- **No cross-backend caching.** Each tool call repeats expansion, repeats fanout. Two `recall` calls in one turn pay double cost — the description tells the model not to do this, but the only enforcement is text in the docstring.
- **Graphiti is queried per-facet.** For each expanded query string the fanout fires one `search_facts` call. With 3 facets + 1 rewritten query that's 4 FalkorDB calls per recall. With Haiku LLM building the graph during ingest, this lane is the most expensive of the five.
- **Subject-safety is one-way.** The deterministic detector and Haiku extractor reject third-party identity facts ([`extract_user_facts.py:67-76`](../backend/memory/hooks/extract_user_facts.py#L67)) before they get written. There's nothing comparable on the read side. If a stale "user is a banker" Graphiti edge exists from before subject-safety landed, it will still surface in `recall`.

## Production state of the lanes

- **Postgres** (observations, open_loops, situation brief) — always live. This is the most reliable lane.
- **Supermemory** — degrades silently when `SUPERMEMORY_API_KEY` is missing ([`clients/supermemory.py:58-69`](../backend/memory/clients/supermemory.py#L58)). Empty list on any error. In prod, key is set; client works.
- **Graphiti / FalkorDB** — `_init_graphiti` ([`clients/graphiti.py:23`](../backend/memory/clients/graphiti.py#L23)) returns None on import or driver failure, and reset_singleton on connection errors. Recently flipped to internal Railway hostname per the deploy comments in `chore: bring working tree in sync to unblock prod deploy`.
- **Calendar** — Postgres mirror synced from Google via Composio ([`db/models.py:178`](../db/models.py#L178)).
- **Procedural rules** — Postgres, three tiers; Tier-2 written nightly by the synthesis worker ([`backend/memory/synthesis/procedural_rules_tier2.py`](../backend/memory/synthesis/procedural_rules_tier2.py)).
- **Web** — Exa-backed, not part of `recall`.

## Hooks — multi-backend write sync

`ALL_HOOKS` ([`backend/memory/hooks/__init__.py:25-30`](../backend/memory/hooks/__init__.py#L25)) runs four hooks in order after every `send_burst`:

1. `save_chat_messages.run` → Postgres `chat_messages`
2. `record_episode.run` → Supermemory unconditionally
3. `ingest_to_graph.run` → Graphiti, gated by three-layer selectivity ([`gates/graph_ingest_gate.py`](../backend/memory/gates/graph_ingest_gate.py))
4. `extract_user_facts.run` → Living Profile (Postgres `users.facts` JSONB) via Haiku, plus offline language detector

These fire in parallel as `asyncio.create_task` ([`donna_runtime/hooks.py:529-536`](../donna_runtime/hooks.py#L529)) — non-blocking. Every send_burst writes to Postgres and Supermemory, conditionally to Graphiti. There's no transactional contract: if Graphiti fails after Supermemory succeeds, you get drift between the two stores.

## My opinion

The unified `recall` is more honest than I expected. RRF over five lanes is a real fusion strategy and the structured hint priority is a good engineering compromise — it gives the deterministic Postgres lane a leg up when the question is obviously structured, while still letting fuzzy lanes vote.

But the moat is only half built.

The biggest gap: **calendar, document chunks, and procedural rules are walled off from the unified surface.** That means the "Maya in chat last week, calendar event tomorrow, Graphiti node for friend" example fails. Calendar isn't in the fanout, period. The model has to call two tools and merge in its head. That's not what a thinking partner does — that's a chatbot with a sidebar.

The second gap: **read-side subject-safety doesn't exist.** All the work went into preventing bad writes. None of it cleans up legacy data on read. If your name was once mis-extracted as Aayam, the fix landed only at write time.

The third gap: **the bitemporal facts table is dark.** It's a beautiful schema with no recall tool. Either delete it or wire it.

I'd consolidate by adding `calendar` and `procedural_rules` lanes to `fanout.py`, dropping `recall_episodic` / `recall_graph` from the tool surface (the model rarely needs them given `recall(query, purpose=...)`), and exposing the bitemporal `get_as_of` as a fourth purpose mode. That gives you one tool that actually delivers cross-source intelligence and keeps the cost discipline tight (one expansion, one fanout, one rerank per turn).

## Verdict

**Partial.** The pipeline exists and does what it says: expand → parallel fanout → RRF rerank across Supermemory + Graphiti + Postgres observations + open_loops + situation brief. That's five of ten backends fused. The other five (calendar, documents, procedural rules, bitemporal facts, web) are siloed behind separate tools, which means the model is doing the cross-source reasoning, not the retrieval layer. For the brand promise of "thinking partner," that's a B-grade. The technical moat is real but only on the lanes most people use; the calendar gap will bite the moment a user asks a time-aware relational question.
