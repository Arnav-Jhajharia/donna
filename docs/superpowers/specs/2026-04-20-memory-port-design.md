# Memory Infra Port — backend-v2 → InstructKr.Claw-Code-main

**Date:** 2026-04-20
**Status:** Design approved, ready for implementation plan
**Scope:** Memory infrastructure ONLY. Tools are initial pass; will be evaluated and iterated separately.

## 1. Goal

Port the nine-layer memory system from `/Users/i3dlab/Documents/NUS/bakchodi/aura/backend-v2/` into `/Users/i3dlab/Downloads/InstructKr.Claw-Code-main/`, adapting the existing LangGraph node-based pipeline to the Claude Agent SDK tool/hook model. Fix the Graphiti reactive-ingest bug (commented imports) by gating ingestion through a Haiku-driven selectivity gate. Produce a working memory layer that can be ingested into and queried end-to-end, after which tools will be evaluated and refined in a follow-up cycle.

## 2. Non-goals

- Ingress (voice/image/document upload pipelines) — not ported
- LangGraph `perceive/` orchestration (triage, broad_retrieval, targeted_retrieval, produce_brief, reason_and_query nodes) — replaced by SDK tool-calling loop
- Donna dispatcher (`donna_model/`), scheduler, delivery, observability subsystems
- Calendar sync (Composio cron) — calendar read is in scope, sync is not
- Non-memory DB tables (DonnaInstance, RunTrace, OAuthToken, DonnaSchedule, SchemaRegistry)
- Tool-surface refinement — tools are a first-pass translation, intentional iteration comes later
- UI/dashboard work

## 3. What gets ported

### 3.1 Clients (verbatim port, light path fixes)
| Source | Target |
|---|---|
| `memory/client.py` | `backend/memory/clients/supermemory.py` |
| `graph_memory/client.py` + `graph_memory/__init__.py` | `backend/memory/clients/graphiti.py` |

### 3.2 User facts / Living Profile (verbatim port)
| Source | Target |
|---|---|
| `user_facts/schema.py` | `backend/memory/user_facts/schema.py` |
| `user_facts/api.py` | `backend/memory/user_facts/api.py` |
| `user_facts/language.py` | `backend/memory/user_facts/language.py` |
| `user_facts/brief_block.py` | `backend/memory/user_facts/rendering.py` |
| `user_facts/observation_writer.py` | `backend/memory/user_facts/observation_writer.py` |

### 3.3 Retrieval pipeline (verbatim port, wrapped as one tool)
| Source | Target |
|---|---|
| `retrieval/expansion.py` | `backend/memory/retrieval/expansion.py` |
| `retrieval/fanout.py` | `backend/memory/retrieval/fanout.py` |
| `retrieval/rerank.py` | `backend/memory/retrieval/rerank.py` |
| `retrieval/pipeline.py` | `backend/memory/retrieval/pipeline.py` |
| `retrieval/types.py` | `backend/memory/retrieval/types.py` |

### 3.4 Nightly synthesis
| Source | Target |
|---|---|
| `background/nightly_profile.py` | `backend/memory/synthesis/living_profile.py` |
| *(new)* | `backend/memory/synthesis/procedural_rules_tier2.py` |

### 3.5 DB models (memory tables only)
Port from `db/models.py`, keeping only:
- `User` (with `facts` and new `living_profile` JSONB columns)
- `Observation`
- `OpenLoop`
- `ProceduralRule`
- `CalendarEntry`
- `ChatMessage`

Target: `backend/db/models.py`. Alembic setup at `backend/db/migrations/`. Initial migration creates all tables + adds `users.living_profile JSONB NULLABLE`.

### 3.6 Perceive node logic (refactored into tools/hooks, not ported verbatim)
| Source logic | New location |
|---|---|
| `perceive/writes.py::write_episode` | `backend/memory/hooks/record_episode.py` |
| `perceive/writes.py::queue_inference` | (dropped — inference happens in nightly synthesis) |
| `perceive/nodes/extract_user_facts.py` | `backend/memory/hooks/extract_user_facts.py` |
| Commented Graphiti ingest in `produce_brief.py`, `writes.py` | `backend/memory/hooks/ingest_to_graph.py` (gated) |
| `perceive/nodes/broad_retrieval.py` lane logic | `backend/memory/tools/*.py` (one tool per lane) |
| `perceive/nodes/targeted_retrieval.py` | `backend/memory/tools/recall_episodic.py` + `recall_graph.py` (model re-calls as needed) |
| `perceive/heuristics.py::is_simple_message` | `backend/memory/gates/graph_ingest_gate.py` (rule layer) |

## 4. Target directory tree

```
InstructKr.Claw-Code-main/
  backend/
    __init__.py
    db/
      __init__.py
      session.py                    # async engine, AsyncSession factory
      models.py                     # User, Observation, OpenLoop,
                                    # ProceduralRule, CalendarEntry, ChatMessage
      migrations/
        env.py
        versions/
          0001_initial_memory_tables.py
    memory/
      __init__.py
      schemas.py                    # shared Pydantic DTOs (FactKey, Confidence, etc.)
      clients/
        __init__.py
        supermemory.py
        graphiti.py
      user_facts/
        __init__.py
        schema.py
        api.py
        language.py
        rendering.py                # renamed from brief_block.py
        observation_writer.py
      retrieval/
        __init__.py
        expansion.py
        fanout.py
        rerank.py
        pipeline.py
        types.py
      tools/
        __init__.py
        recall_episodic.py
        recall_graph.py
        recall_document_chunks.py
        recall_chat_thread.py
        list_observations.py
        list_open_loops.py
        list_rules.py
        list_calendar.py
        log_observation.py
        track_open_loop.py
        close_open_loop.py
        update_living_profile.py
        smart_recall.py             # wraps retrieval/pipeline.py
      hooks/
        __init__.py
        save_chat_messages.py
        record_episode.py
        ingest_to_graph.py          # uses gates/graph_ingest_gate.py
        extract_user_facts.py
      gates/
        __init__.py
        graph_ingest_gate.py
      synthesis/
        __init__.py
        living_profile.py
        procedural_rules_tier2.py
        prompts/
          living_profile_synthesis.md
          tier2_rules_synthesis.md
          fact_extraction.md
          graph_ingest_gate.md
      tests/
        __init__.py
        test_supermemory_client.py
        test_graphiti_client.py
        test_user_facts.py
        test_retrieval_pipeline.py
        test_tools_*.py
        test_hooks_*.py
        test_gate.py
        test_integration_end_to_end.py
  docs/
    memory.md
    OPEN_QUESTIONS.md
    superpowers/specs/2026-04-20-memory-port-design.md  # this file
```

## 5. The 12 tools

Every tool follows `primitives.md` template: description (when to use / when NOT to use), input schema, example trigger, return shape (`status: ok | no_hits | degraded` + payload).

### Read tools
| Tool | Backend | Primary use |
|---|---|---|
| `recall_episodic` | Supermemory episodes | "What did we say about X?" |
| `recall_graph` | Graphiti | "What do I know about entity/person X?" |
| `recall_document_chunks` | Supermemory chunks | Doc Q&A |
| `recall_chat_thread` | Postgres `chat_messages` | Chat history beyond last 5 |
| `list_observations` | Postgres `observations` | Countable events (meals, mood, sleep) |
| `list_open_loops` | Postgres `open_loops` | "What's owed / owing" |
| `list_rules` | Postgres `procedural_rules` (Tier 2) | Inferred rules |
| `list_calendar` | Postgres `calendar_entries` | Upcoming events |
| `smart_recall` | `retrieval/pipeline.py` (expansion→fanout→rerank) | Fuzzy "I don't know where to look" |

### Write tools
| Tool | Backend | Primary use |
|---|---|---|
| `log_observation` | Postgres `observations` | Model decides "this is a countable fact worth tracking" |
| `track_open_loop` | Postgres `open_loops` | Detect unresolved thread |
| `close_open_loop` | Postgres `open_loops` | Detect resolution of prior loop |
| `update_living_profile` | Postgres `users.living_profile` | Targeted patch between nightly runs |

Tool bodies live in `backend/memory/tools/*.py`. Registration for the SDK (via `@tool` decorator or MCP server) happens in the runtime wiring step (Phase 6) — each tool exports a callable the SDK can invoke.

## 6. The 4 hooks

All hooks are `PostToolUse` on `send_burst`, except `save_chat_messages` which also handles inbound and runs first. All run as `asyncio.create_task(...)` to avoid blocking response delivery.

| Hook | Trigger | Behavior |
|---|---|---|
| `save_chat_messages` | Inbound ingress + PostToolUse(send_burst) | Writes inbound + outbound to `chat_messages` table. Synchronous relative to other hooks (they may reference its IDs). |
| `record_episode` | PostToolUse(send_burst) | Supermemory `add_episode`. Unconditional. |
| `ingest_to_graph` | PostToolUse(send_burst) | **Gated** by `should_ingest_to_graph`. Only fires if gate returns True. Calls `graphiti.ingest_episode`. |
| `extract_user_facts` | PostToolUse(send_burst) | Haiku subagent extracts high-confidence facts → `update_user_fact` writes to `User.facts`. |

Registration: extend `donna_runtime/hooks.py` with hook callbacks that import from `backend.memory.hooks`.

## 7. The selective-ingest gate

`backend/memory/gates/graph_ingest_gate.py`

**Decision layers:**
1. **Rule-based fast rejection** (zero LLM cost):
   - Inbound length < 20 chars
   - Inbound matches ambient filler set (`{"k", "lol", "ok", "haha", "bro", ...}`)
   - Turn terminated with `stay_silent` and used only 1 tool call
2. **Rule-based fast acceptance**:
   - `send_burst` with ≥ 2 outbound messages
   - Any turn that called `recall_graph` or `recall_episodic` (the turn needed memory, so it's worth remembering)
3. **Haiku judgment** for the fuzzy middle:
   - Prompt at `synthesis/prompts/graph_ingest_gate.md`
   - Inputs: inbound text, outbound messages, tool names, terminator
   - Output: `{worth_ingesting: bool, reason: str}`
   - Decisions logged for later tuning

**Target outcome:** 40–60% of turns ingested. Document ratio and tuning guide in `docs/memory.md`.

## 8. Nightly synthesis

Runs via a simple APScheduler-style cron in `backend/memory/synthesis/` — but scheduler wiring is out of scope for this port; for now, expose `synthesize_nightly_profile(user_id)` and `synthesize_tier2_rules(user_id)` as callable functions. Runtime scheduling follows in a later iteration.

**`living_profile.py`:** Ported from `background/nightly_profile.py`. Inputs swapped to use new clients. Writes to `users.living_profile` (new column) rather than `users.facts['nightly_profile']` (legacy). Backfill migration copies legacy → new on initial migration.

**`procedural_rules_tier2.py`:** New. Inputs: observations since last synthesis, existing Tier 2 rules. Output: up to 12 inferred rules, replaces Tier 2 wholesale (ADR 0008 semantics preserved).

## 9. Runtime integration (minimal surface change)

Two touchpoints in `donna_runtime/`:

1. **`donna_runtime/tool_logic.py`**: replace fake-data returns for `recall_episodic_result` / `read_tracker_result` with real calls into `backend.memory.tools.*`. (Per user directive: option A — fakes gone, real data end-to-end.)
2. **`donna_runtime/hooks.py`**: register the four memory hooks against the SDK's PostToolUse event for `send_burst`.

Everything else (`runner.py`, `options.py`, `session_store.py`, `audit.py`) is untouched.

`donna_runtime/prompt.py` gains one line: load Living Profile via `backend.memory.user_facts.rendering.render_user_model_block` and splice it into the system prompt.

## 10. Environment variables

Added to `.env`:
- `DATABASE_URL` (Postgres async: `postgresql+asyncpg://...`)
- `SUPERMEMORY_API_KEY`
- `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_PASSWORD` (optional)
- `OPENAI_API_KEY` (Graphiti's embedder)

If any are missing at import time, the relevant client logs a warning and its tools/hooks return `status: degraded` rather than crashing.

## 11. Testing strategy

**Per-backend unit tests:**
- Isolation: user A's data never visible to user B's queries
- Empty state: queries return `status: no_hits`, never exceptions
- Degraded: backend unreachable → `status: degraded`, runtime continues

**Gate tests:**
- 10 must-reject golden cases (rule layer)
- 10 must-accept golden cases (rule layer)
- Fuzzy-middle set with recorded Haiku verdicts (snapshot tests)

**Integration test** (`test_integration_end_to_end.py`):
- User A sends inbound → SDK loop runs → model calls recall tool → `send_burst` → all 4 hooks fire → verify:
  - `chat_messages` has inbound + outbound
  - Supermemory has new episode
  - FalkorDB has new graph nodes iff gate accepted
  - `User.facts` updated if high-confidence fact detected
- Second turn: system prompt includes updated Living Profile
- Third turn with "what did I say earlier?" — `recall_episodic` returns the hit

## 12. Known pitfalls to preserve during port

- Graphiti `_route_to_user_db()` call before every query (multi-tenant FalkorDB routing workaround)
- `group_id = user_id.replace("-", "")` normalization
- Supermemory `container_tag` per-user scoping
- `User.facts` source-ranking resolution in `update_user_fact`
- Indexes on `observations (user_id, type, event_time)`

## 13. Open questions (deferred, not blocking)

Captured in `docs/OPEN_QUESTIONS.md` after implementation:
- Tool count: 12 feels high for the SDK model's selection stability — may consolidate to ~6–8 after eval
- `smart_recall` vs individual `recall_*` tools: which does the model actually pick? Eval answers this.
- Gate threshold tuning: 40–60% target is a guess; will measure post-ingestion
- `log_observation` tool vs auto-extraction hook: currently tool-only; may add Haiku auto-fan later
- Scheduler for nightly jobs: deferred

## 14. Deliverables

1. All files under `backend/`
2. Alembic migration creating memory tables + `living_profile` column
3. Test suite passing: `pytest backend/tests -v`
4. `docs/memory.md` — nine-layer model, tools, hooks, gate tuning guide
5. `docs/OPEN_QUESTIONS.md` — what to evaluate in the next cycle
6. Integration test output pasted in final summary

## 15. Execution phases

- **Phase 0** — Scaffold `backend/`, deps, alembic, initial migration
- **Phase 1** — Port clients (Supermemory, Graphiti) + user_facts
- **Phase 2** — Port retrieval pipeline
- **Phase 3** — Implement 12 tools
- **Phase 4** — Implement gate
- **Phase 5** — Implement 4 hooks
- **Phase 6** — Implement nightly synthesis callables
- **Phase 7** — Wire into `donna_runtime/` (tool_logic, hooks, prompt)
- **Phase 8** — Tests + integration test + docs

Pause ONLY on blocking external dependencies (missing creds, unreachable DB). Report at each phase boundary.
