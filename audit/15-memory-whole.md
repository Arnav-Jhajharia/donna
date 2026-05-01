# 15 · Memory, the whole picture

The complete view. CLAUDE.md says ten backends. Here's what's actually wired, what writes to it, what reads from it, what ages out, and where the seams are.

## The ten backends — file by file

| # | Backend | Where it lives | Read tools | Write surfaces |
|---|---|---|---|---|
| 1 | Graphiti / FalkorDB (entities + edges) | [`backend/memory/clients/graphiti.py`](../backend/memory/clients/graphiti.py) | `recall_graph`, fanout lane in `recall` | `ingest_episode` via `ingest_to_graph` hook (gated) |
| 2 | Supermemory episodic | [`backend/memory/clients/supermemory.py:74`](../backend/memory/clients/supermemory.py#L74) | `recall_episodic`, fanout lane in `recall` | `record_episode` hook, every send_burst |
| 3 | Supermemory document chunks | [`clients/supermemory.py:139`](../backend/memory/clients/supermemory.py#L139) | `recall_document_chunks` only | document upload pipeline at [`backend/memory/ingest/documents.py`](../backend/memory/ingest/documents.py) |
| 4 | Procedural rules (3 tiers) | [`db/models.py:65`](../db/models.py#L65), [`backend/memory/synthesis/procedural_rules_tier2.py`](../backend/memory/synthesis/procedural_rules_tier2.py) | rendered into system prompt; `list_rules` tool | nightly Tier-2 synthesis worker, manual Tier-1 / Tier-3 |
| 5 | Observations | [`db/models.py:77`](../db/models.py#L77) | `read_tracker`, `list_observations`, fanout lane | `log_observation` ([`tools/log_observation.py`](../backend/memory/tools/log_observation.py)) via `remember(kind="observation")` |
| 6 | Open loops | [`db/models.py:121`](../db/models.py#L121) | `list_open_loops`, fanout lane | `track_open_loop`, `close_open_loop` |
| 7 | User facts / Living Profile | [`db/models.py:39-44`](../db/models.py#L39), [`user_facts/api.py`](../backend/memory/user_facts/api.py), [`user_facts/rendering.py`](../backend/memory/user_facts/rendering.py) | rendered into system prompt at turn start | `extract_user_facts` Haiku hook, `deterministic_fact_detector` pre-turn, `update_user_fact` API |
| 8 | Chat messages | [`db/models.py:54`](../db/models.py#L54) | `recall_chat_thread` ([`tools/recall_chat_thread.py`](../backend/memory/tools/recall_chat_thread.py)) | `save_chat_messages` hook |
| 9 | Calendar | [`db/models.py:178`](../db/models.py#L178) | `list_calendar`, `check_calendar` | sync from Google via Composio integration |
| 10 | Web | `backend/web/...`, Exa | `web_search`, `agentic_web_search`, `research` | not persistent in the same sense |

Plus a hidden 11th: **bitemporal facts** ([`db/models.py:140`](../db/models.py#L140), [`backend/memory/facts/bitemporal.py`](../backend/memory/facts/bitemporal.py)). It exists, has migrations, has full record/update/supersede/get_as_of API, and no tool surface.

Plus a hidden 12th: **donna_schedule** ([`db/models.py:218`](../db/models.py#L218)) — every reminder is a memory entry, but isn't part of "memory" mentally.

Plus a hidden 13th: **attentions** ([`db/models.py:489`](../db/models.py#L489)) — proactive intent state, but not searched.

So the count is squishier than the doc says. The honest count is "six Postgres tables, two Supermemory containers, one FalkorDB graph, one calendar mirror." Web is reach, not memory.

## Migrations

Twelve numbered Alembic revisions ([`backend/db/migrations/versions/`](../backend/db/migrations/versions/)):

- `0001_initial_memory_tables` — observations, open_loops, schema_registry
- `0002_bitemporal_facts` — facts table + indices
- `0003_image_tool_events`
- `0004_integrations_and_emails`
- `0005_proactive_pings`
- `0006_donna_schedule_attention_link`
- `0007_attentions`
- `0008_dashboard_manifests`
- `0009_auth_otps`
- `0010_integration_redirect_url`
- `0011_open_loops_due_at` — new field for the DeadlineProposer
- `0012_proactive_engine_v1` — Proposers + Attentions + ProactivePings tables

Schema is dense and current. No major structural debt visible.

## Write disciplines

`ALL_HOOKS` ([`backend/memory/hooks/__init__.py`](../backend/memory/hooks/__init__.py)) runs four hooks after every `send_burst`, fired as `asyncio.create_task` so they don't block the user:

1. `save_chat_messages` — every inbound + outbound to Postgres `chat_messages`. Idempotent via `chat_already_persisted` flag.
2. `record_episode` — every turn body to Supermemory, unconditional. Will silently no-op if Supermemory is down.
3. `ingest_to_graph` — gated by `should_ingest_to_graph` ([`backend/memory/gates/graph_ingest_gate.py:100`](../backend/memory/gates/graph_ingest_gate.py#L100)). Three layers: fast-reject (short / ambient filler), fast-accept (multi-message burst, recall tools used), Haiku judgment for the middle.
4. `extract_user_facts` — Haiku reads inbound + current facts, produces up to 3 extractions, applies subject-safety filter, writes via `update_user_fact`.

Plus a pre-turn hook in `donna_runtime/brain.py:50`: `deterministic_fact_detector.run(user_id, inbound)`. Regex patterns for "my name is X / I'm a X / I live in X" — fast precise path.

The same fact can land in **multiple** stores legitimately:
- `record_episode` always writes to Supermemory.
- `ingest_to_graph` writes the same turn body to Graphiti when the gate passes.
- `extract_user_facts` writes structured facts to the Living Profile JSONB.

So a single user message saying "I just moved to Paris" produces, in parallel: a chat message row, a Supermemory episode, a Graphiti edge (probably), a Living Profile `current_city: paris` fact, and possibly a deterministic-detector fact. **There is no dedup between stores.** Each backend is the source of truth for its own shape; they overlap on purpose because they answer different shapes of question.

The `remember` tool ([`donna_runtime/tools.py:1018`](../donna_runtime/tools.py#L1018)) is the user-explicit write surface. Routes by `kind`:
- `observation` → `log_observation` (Postgres)
- `open_loop` / `commitment` → `track_open_loop` (Postgres)
- `loop_closed` → `close_open_loop`
- `timezone` → `set_timezone`
- `fact` and `preference` are **rejected** with a clear error — those are reserved for the post-turn extractor only.

This is correct discipline. The model can't shortcut around the Living Profile machinery.

## Read disciplines

Three render targets feed memory directly into the prompt without a tool call:

- **USER MODEL** — `load_and_render(user_id)` ([`user_facts/rendering.py:424`](../backend/memory/user_facts/rendering.py#L424)) renders Living Profile + facts. CLAUDE.md guarantees no auto-reload mid-turn.
- **TODAY block** — calendar today + today's observations + active open loops ([`donna_runtime/context_builder.py:140`](../donna_runtime/context_builder.py#L140)).
- **RECENT CHAT** — recent ChatMessage rows.
- **SITUATION BRIEF** — when present, lifted from `users.living_profile["situation_brief"]`.

Everything else requires a tool call. The model is told (in `recall` description and CLAUDE.md): if USER MODEL or SITUATION BRIEF already answers it, don't call recall.

## Bitemporal facts — the dead-letter store

[`backend/memory/facts/bitemporal.py`](../backend/memory/facts/bitemporal.py) has:
- `record_fact` — insert current belief
- `update_fact` — close old t_valid_to, real-world state changed
- `supersede_fact` — close old t_recorded_to, we were wrong
- `get_current`, `get_as_of`, `list_history`

This is genuinely good design. Two time axes, the standard bitemporal trick. But there's no tool that calls these. The only caller I can find is `record_timezone_fact` (referenced in the prompt but I didn't trace it to use). The Living Profile is single-temporal: most recent value wins. So Donna can't answer "where did I live in 2023" — only "where do you live now."

## Decay and freshness

- Observations have `event_time` indexed, queried with `since = utcnow() - timedelta(days=14)` by default in fanout ([`fanout.py:107`](../backend/memory/retrieval/fanout.py#L107)).
- Living Profile situation brief is regenerated by `synthesis_worker` nightly + morning digest.
- Procedural rules Tier-2 fully replaced each nightly run.
- Supermemory episodes have no aging logic on our side — Supermemory itself ranks.
- Graphiti has bitemporal valid_at / invalid_at on edges; we surface but don't filter.
- Calendar entries are not aged — they live until manually pruned.
- Chat messages are append-only forever. No retention policy.

This will be a problem at scale. Chat messages especially will get fat fast.

## Privacy and scope

Every read query filters by `user_id`. Spot checks:
- `fanout._search_observations:101` — `Observation.user_id == user_id`
- `fanout._search_open_loops:218` — `OpenLoop.user_id == user_id`
- `clients/graphiti._safe_group_id` — `user_id.replace("-","")`. Different group_id per user. Routed via `_route_to_user_db` before every query.
- Supermemory uses `container_tag=user_id`.

I see no obvious cross-user leakage path. The Graphiti dance is paranoid for the right reason.

The deterministic + Haiku subject-safety logic ([`extract_user_facts.py:67`](../backend/memory/hooks/extract_user_facts.py#L67)) only protects against extracting third-party identity facts onto the user. It does not protect against, say, the user mentioning their friend's secret in a way that ends up in Graphiti as a generic fact tagged to the user. That's a category we don't currently defend.

## Production state

- Postgres — fine, primary.
- Supermemory — needs `SUPERMEMORY_API_KEY`; degrades to no-op if missing. Set in prod.
- Graphiti FalkorDB — needs `FALKORDB_HOST/PORT/USERNAME/PASSWORD`; defaults `localhost:6379`. Just got the internal Railway hostname fix per recent commits ([`02-timezones.md`](./02-timezones.md) and the unblock-prod-deploy commit). Haiku LLM does the entity extraction inside Graphiti.
- Cost: each turn fires four hooks; expansion + 5 fanout lanes on every recall call. The `_LANE_TIMEOUT = 8.0` per lane keeps the worst case bounded.

## Cost discipline

CLAUDE.md targets "low single-digit cents" per reactive turn. Risks I see:
- Graphiti search fires once per facet × per recall call. With 4 expanded queries that's 4 FalkorDB calls + Haiku inside Graphiti.
- Expansion is Haiku, ~one turn per recall.
- Fanout to Supermemory is one HTTP call per facet (4 again).
- Living Profile rendering on every turn — pulled from cached Postgres row, cheap.
- The post-turn extractor is Haiku per turn — bounded.

The risk is recall hot paths in long sessions. The tool description tells the model "do NOT call twice in the same turn" but enforcement is text only.

## Stress and replay

- [`scripts/stress_memory_system.py`](../scripts/stress_memory_system.py) — full-system harness. Seeds disposable users, refreshes situation brief, probes tools, runs Sonnet turns, scores artifacts.
- [`scripts/replay_memory_diary.py`](../scripts/replay_memory_diary.py) — diary-style replay.
- [`scripts/_out/memory_stress_*`](../scripts/_out/) — outputs from recent runs (currently in untracked status).

These are real harnesses. They produce JSON artifacts you can grade. Used as part of `/eval` runs.

## My opinion

The architecture is honest about being many backends, **but it tells itself a small lie about being unified**: `recall` only fuses five of the ten. Calendar, documents, procedural rules, bitemporal facts, and web are siloed. The "1 store with a recall facade" is half-built.

The biggest unforced lie: **the bitemporal facts table is shipped but not used**. A whole migration, a whole module, full bitemporal API, no read tool, no write call from anywhere user-visible. Either that's the product (and we should expose it) or it's tech debt (delete it).

The second issue: **chat messages have no retention strategy.** They will compound forever. At 100 active users sending 50 messages a day, that's ~1.8M rows per year, all queried by user_id with a recency window. It will work for a long time but you'll wake up one day with a slow `chat_messages` table.

The third: **write fanout has no transaction.** Hooks are `asyncio.create_task` and any one can fail silently. An observation can land in Postgres without ever reaching Supermemory's episode store. The hooks are best-effort. For a "thinking partner with persistent memory" that's a real disclosure — memory is durable in Postgres and probabilistic everywhere else.

The right consolidation, in priority order:
1. Add calendar + procedural_rules + document chunks lanes to `fanout.py`. One recall call should hit eight backends, not five.
2. Either expose `get_as_of` as `recall(purpose="historical", at=...)` or delete the bitemporal store.
3. Add a chat-messages compactor (summarize older threads, drop raw rows beyond N days).
4. Add a read-side subject-safety scrub for Graphiti edges that predate the write-side guard.

The thing the system gets right: **render-vs-search separation.** Living Profile, TODAY, RECENT CHAT, SITUATION BRIEF go in the prompt; everything else is a tool call. That's the correct discipline and it explains why per-turn cost stays low.

## Verdict

**Strong but incomplete.** The schemas are real, the hooks fire, the unified `recall` actually fuses five lanes via RRF, subject-safety is a serious effort on writes, bitemporal facts has a beautiful API. But the recall surface only covers half the backends, the bitemporal store is orphaned, and there's no transactional contract between hooks. The brand promise of "persistent memory" is delivered for the lanes that matter most (chat, observations, episodes, graph, profile); "thinking partner" is one calendar-fanout away from being properly true.
