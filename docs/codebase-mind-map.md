# Codebase Mind Map

Generated from the current repo state on 2026-04-22.

## High-Level Map

```mermaid
mindmap
  root((Donna / Claw Code))
    Live WhatsApp Runtime
      api/main.py
        FastAPI app
        Webhook verify and handler
        Per-phone cancel-and-restart dispatcher
        Durable inbound replay
      ingress/
        payload.py transport-agnostic dataclasses
        whatsapp.py WhatsApp webhook parser and media downloader
        node.py reply context and URL enrichment
      api/graph.py
        payload-to-state adapter
        phone-to-user lookup
      delivery/
        messages.py channel-agnostic outbound types
        whatsapp.py WhatsApp Cloud renderer and sender
      db/
        models.py production-ish app tables
        inbound.py durable inbox helpers
        session.py root DB engine
        migrations.py create_all startup helper
    Donna Agent Runtime
      donna.py CLI entrypoint
      stream_donna.py raw SDK stream inspector
      donna_runtime/
        config.py model and tool policy
        prompt.py Donna system prompt
        options.py ClaudeAgentOptions and MCP server wiring
        runner.py Agent SDK query loop and tracing
        brain.py WhatsApp bridge around runner
        tools.py MCP tools exposed to model
        tool_logic.py SDK-free tool implementations
        hooks.py pre/post tool hooks and memory hook fanout
        tracing.py JSONL TurnTrace
        session_store.py file and DB SDK session mapping
    Memory Backend
      backend/memory/
        tools/ model-callable memory/action tools
        hooks/ post-turn persistence and extraction
        retrieval/ smart_recall pipeline
        clients/ Supermemory and Graphiti adapters
        user_facts/ living profile facts
        gates/ graph ingestion decisioning
        synthesis/ living profile and procedural rules synthesis
      backend/db/
        models.py memory-subset tables
        session.py backend DB engine
        migrations/ Alembic memory migration
      External stores
        Postgres
        Supermemory
        Graphiti / FalkorDB
        Anthropic / OpenAI structured calls
    Attention Harness
      donna/attention/
        vocabulary.py closed source/card enums
        schema.py AttentionSpec and Attention records
        normalize.py raw intent normalization
        retrieve.py TF-IDF gold-example retrieval
        author.py spec authoring and ping shortcut
        dry_run.py source fetchers and previews
        harness.py normalize -> retrieve -> author -> dry_run
        tools.py create/list/tick/pause/resume APIs
        propose.py ambient-signal candidate generation
        promote.py shadow promotion lifecycle
        scheduler.py env-gated interval scheduler
        cli.py terminal interface
    Dashboard
      dashboard/web/
        app/page.tsx main mobile dashboard route
        app/generator/page.tsx generator route
        app/moments/page.tsx moments route
        lib/plan.ts DashboardPlan contract and validation
        lib/getPlan.ts static fixture seam
        lib/generator.ts future generated-state composer
        components/DashboardRenderer.tsx block switchboard
        components/blocks/ visual block components
      dashboard/project/
        exported design prototypes
        design system docs and CSS
    Tests and Experiments
      tests/ active Donna runtime tests
      backend/tests/ memory backend tests
      donna/attention/tests/ attention harness tests
      scripts/ attention stress and ablation scripts
```

## Primary Live Runtime Flow

This is the current user-message path for WhatsApp traffic.

```mermaid
flowchart TD
  WA[Meta WhatsApp webhook] --> API[api/main.py FastAPI /webhook]
  API --> Relay{relay configured?}
  Relay -->|all traffic| RelayTarget[forward to relay_url]
  Relay -->|dev phones| DevRelay[forward matching phones to dev_relay_url]
  Relay -->|process here| Parse[ingress/whatsapp.py parse_webhook]

  Parse --> Payload[IngressPayload]
  Payload --> Inbox[db/inbound.py insert queued row]
  Inbox --> Dispatch[per-phone cancel-and-restart dispatcher]
  Dispatch --> Merge[_merge_payloads for rapid-fire messages]

  Merge --> State[api/graph.py state_from_payload]
  State --> UserLookup[api/graph.py user_lookup]
  UserLookup --> RootDB[(root db/ Postgres)]
  UserLookup --> Enrich[ingress/node.py enrich]
  Enrich --> ReplyCtx[reply_to lookup in chat_messages]
  Enrich --> UrlFetch[URL excerpt fetch]

  Enrich --> SaveUser[api/main.py save user ChatMessage]
  SaveUser --> Brain[donna_runtime/brain.py donna_turn]
  Brain --> Runner[donna_runtime/runner.py traced_donna_turn]
  Runner --> Options[donna_runtime/options.py build_options]
  Options --> Prompt[donna_runtime/prompt.py system prompt]
  Options --> MCP[SDK MCP server donna-tools]
  MCP --> Tools[donna_runtime/tools.py]
  Tools --> ToolLogic[donna_runtime/tool_logic.py]
  Runner --> SDK[Claude Agent SDK query]

  SDK --> SendBurst[mcp__donna__send_burst]
  SendBurst --> Buffer[_OUTBOUND_BUFFER]
  SendBurst --> MemoryHooks[donna_runtime/hooks.py _fire_memory_hooks]
  MemoryHooks --> BackendHooks[backend/memory/hooks/]
  BackendHooks --> BackendDB[(backend/db Postgres)]
  BackendHooks --> Supermemory[(Supermemory)]
  BackendHooks --> Graphiti[(Graphiti/FalkorDB)]

  Buffer --> Outbound[delivery/messages.py objects]
  Outbound --> SaveAssistant[save rendered assistant ChatMessage]
  SaveAssistant --> Send[delivery/whatsapp.py send_many]
  Send --> WAAPI[WhatsApp Cloud API]
  Send --> MarkProcessed[db/inbound.py mark_processed]
```

## Runtime Components

| Area | Where | Role | Main inbound deps | Main outbound deps |
|---|---|---|---|---|
| FastAPI webhook | `api/main.py` | Receives WA webhook, durable inbox insert, dispatch coordination, DB persistence, delivery | `ingress/`, `api/graph.py`, `db/` | `donna_runtime.brain`, `delivery.whatsapp` |
| State adapter | `api/graph.py` | Converts `IngressPayload` to flat state and resolves phone to user | `ingress.payload`, root `db/` | state dict consumed by enrichment/brain |
| Ingress adapter | `ingress/whatsapp.py` | Parses WA payloads, dedups, downloads media, normalizes message types | Meta webhook JSON, `config.py` | `IngressPayload` |
| Ingress enrichment | `ingress/node.py` | Adds reply context and URL excerpts | root `db.ChatMessage`, HTTP URLs | enriched state |
| Delivery model | `delivery/messages.py` | Channel-independent outbound dataclasses | `donna_runtime.tool_logic` | channel renderers |
| WhatsApp delivery | `delivery/whatsapp.py` | Renders outbound objects to WA Cloud API JSON and sends sequentially | `delivery.messages`, `config.py` | Meta Graph API |
| Donna CLI | `donna.py` | Local CLI for running, auditing, health, LangSmith smoke tests | `donna_runtime/*` | Agent SDK runner |
| Brain bridge | `donna_runtime/brain.py` | Wraps the SDK turn for the WhatsApp pipeline and captures `send_burst` output | state dict, session store, runner | `_outbound`, `_turn_trace` |
| SDK runner | `donna_runtime/runner.py` | Executes `claude_agent_sdk.query`, records trace, persists session ids | `options.py`, `hooks.py`, `tracing.py` | `TurnTrace`, optional WA delivery |
| SDK options | `donna_runtime/options.py` | Builds `ClaudeAgentOptions`, MCP server, tool policy, hooks | `config.py`, `prompt.py`, tool lists | Claude Agent SDK |
| Model tools | `donna_runtime/tools.py` | MCP tool wrappers seen by the model | current trace/user context | backend memory tools, outbound buffer |
| Tool logic | `donna_runtime/tool_logic.py` | Pure Python implementations for recall/read/send/silence | backend memory tools, delivery dataclasses | MCP text results, outbound buffer |
| Hooks | `donna_runtime/hooks.py` | Trace pre/post tool hooks and async post-turn memory fanout | `TurnTrace`, contextvars | `backend.memory.hooks.ALL_HOOKS` |
| Runtime tracing | `donna_runtime/tracing.py` | JSONL turn traces and audit inputs | runner message stream | trace file |
| Runtime session store | `donna_runtime/session_store.py` | File-backed CLI sessions and root-DB production sessions | `.donna_sessions.json`, root `db.UserSession` | SDK resume ids |

## Memory Backend Components

| Area | Where | Role |
|---|---|---|
| Tool registry | `backend/memory/tools/__init__.py` | Names the 12 backend memory/action tools. |
| Retrieval tools | `recall_episodic.py`, `recall_graph.py`, `recall_document_chunks.py`, `smart_recall.py`, `recall_chat_thread.py` | Read from Supermemory, Graphiti, document chunks, chat DB, or combined retrieval. |
| State/action tools | `list_observations.py`, `log_observation.py`, `list_open_loops.py`, `track_open_loop.py`, `close_open_loop.py`, `list_rules.py`, `list_calendar.py`, `update_living_profile.py` | CRUD-ish user memory and structured state tools. |
| Smart recall pipeline | `backend/memory/retrieval/pipeline.py` | `expand_query -> fanout -> merge_and_rerank`. |
| Fanout | `backend/memory/retrieval/fanout.py` | Searches Supermemory and Graphiti concurrently per expanded query. |
| Structured LLM helper | `backend/memory/retrieval/structured.py` | Shared typed call wrapper for extraction/synthesis. |
| Post-turn hooks | `backend/memory/hooks/` | Save chat, record episode, ingest graph facts, extract user facts after `send_burst`. |
| Supermemory client | `backend/memory/clients/supermemory.py` | Adds/searches episodic memories and document chunks; degrades if key missing. |
| Graphiti client | `backend/memory/clients/graphiti.py` | Ingests/searches per-user graph facts in FalkorDB; normalizes group ids. |
| User facts | `backend/memory/user_facts/` | Fact schema, update resolution, rendering living profile blocks. |
| Synthesis | `backend/memory/synthesis/` | Living profile and procedural rules synthesis. |
| Memory DB | `backend/db/` | Separate memory-focused SQLAlchemy models/session/Alembic migration. |

Important boundary: the live WhatsApp path imports root `db.*`, while the memory backend imports `backend.db.*`. Those schemas overlap but differ.

## Attention Harness Components

```mermaid
flowchart LR
  Intent[raw standing instruction] --> Normalize[normalize.py]
  Normalize --> Retrieve[retrieve.py gold-example TF-IDF]
  Retrieve --> Author[author.py AttentionSpec authoring]
  Author --> DryRun[dry_run.py source fetch and preview]
  DryRun --> Result[harness.py PipelineResult]

  Proposers[propose.py ambient proposers] --> Intent
  Result --> Store[store.py local AttentionStore]
  Store --> Tools[tools.py create/list/tick APIs]
  Store --> Promote[promote.py shadow cycle]
  Scheduler[scheduler.py env-gated jobs] --> Proposers
  Scheduler --> Promote
```

Notes:

- The main attention pipeline is `normalize -> retrieve -> author -> dry_run`.
- `remind me...` style intents short-circuit into `card=ping`.
- Calendar source can use `backend/memory/tools/list_calendar.py`; most other sources are fixture-backed.
- Shadow mode exists in schema/store/promote flow, but durable production scheduling is still explicitly future work.

## Dashboard Components

```mermaid
flowchart TD
  Page[dashboard/web/app/page.tsx] --> GetPlan[lib/getPlan.ts]
  GetPlan --> Fixture[lib/plans/morning-aarav.ts]
  Fixture --> Plan[lib/plan.ts DashboardPlan]
  Plan --> Validate[validatePlan]
  Page --> Renderer[components/DashboardRenderer.tsx]
  Renderer --> TopBar[components/TopBar.tsx]
  Renderer --> Blocks[components/blocks/*]

  GeneratorRoute[app/generator/page.tsx] --> GeneratorLib[lib/generator.ts]
  MomentsRoute[app/moments/page.tsx] --> PlanFixtures[lib/plans/*]
  DesignPrototypes[dashboard/project/] -. visual source .-> Blocks
```

The dashboard is currently a Next.js app using static plan fixtures. `lib/getPlan.ts` is the seam where memory/LLM-generated dashboard plans are expected to plug in later.

## Data Stores And External Services

| Store/service | Used by | Purpose |
|---|---|---|
| Root Postgres via `db/session.py` | `api/main.py`, `api/graph.py`, `ingress/node.py`, `donna_runtime/session_store.py` | Live WhatsApp users, chat messages, inbound inbox, SDK session ids, broader app tables. |
| Backend Postgres via `backend/db/session.py` | `backend/memory/tools/*`, `backend/memory/user_facts/*`, `backend/memory/synthesis/*` | Memory subset tables used by backend memory tests and tools. |
| `.donna_sessions.json` | `donna.py`, `donna_runtime/session_store.py` | Local CLI user-id to Claude SDK session-id mapping. |
| `donna_traces.jsonl` | `donna_runtime/tracing.py`, `donna.py --audit-only` | Local turn traces and policy audit input. |
| WhatsApp Cloud API | `ingress/whatsapp.py`, `delivery/whatsapp.py` | Media download, typing indicators, outbound sends. |
| Claude Agent SDK | `donna_runtime/runner.py`, `donna_runtime/options.py` | Main agent loop and MCP tool execution. |
| LangSmith | `donna_runtime/langsmith_tracing.py` | Optional tracing around turns/tools/hooks. |
| Supermemory | `backend/memory/clients/supermemory.py` | Episodic memory and document chunk search. |
| Graphiti/FalkorDB | `backend/memory/clients/graphiti.py` | Per-user knowledge graph ingestion/search. |
| Anthropic/OpenAI structured calls | `backend/memory/retrieval/structured.py`, attention authoring/normalization paths | Extraction, synthesis, and spec authoring. |

## Cleanup Hot Spots

These are the highest-friction edges I noticed while mapping the repo:

1. **Two DB packages with divergent schemas.** Root `db/models.py` has production/app tables like `InboundMessage`, `UserSession`, `DonnaInstance`, `RunTrace`, and `OAuthToken`; `backend/db/models.py` has a trimmed memory subset. The live API path uses root `db`, while memory tools use `backend.db`.
2. **`donna_runtime/brain.py` imports DB session helpers but calls file-session helper names.** It imports `resolve_session_id_db` and `save_user_session_db`, but calls `resolve_session_id(...)` and `save_user_session(...)`. As written, the live WhatsApp brain path should fall into the outer API fallback before the SDK turn starts.
3. **WhatsApp send return contract mismatch.** `api/main.py` expects `wamids = await _wa.send_many(...)` and uses `wamids[0]` for assistant message backfill, but `delivery/whatsapp.py::send_many` returns `None`, and `send`/`_post` do not surface message ids.
4. **Memory hooks write through `backend.db`, while the live webhook saves chat through root `db`.** That can split conversation history depending on which path wrote it.
5. **`donna_runtime.config` defaults to `tool_mode="fake"`.** That is useful for tests/prototype runs, but it means the default runtime does not expose the real `backend/memory` tools unless configuration changes.
6. **Dashboard is not wired to backend data yet.** `dashboard/web/lib/getPlan.ts` returns a static fixture; `DashboardPlan` is a good contract, but integration is still a seam.
7. **Attention is mostly a harness, not integrated into the live WhatsApp runtime.** It has CLI/store/scheduler pieces, but no obvious call from `api/main.py` or `donna_runtime` into attention creation/ticking.

## Suggested Ownership Boundaries

- Keep `api/`, `ingress/`, `delivery/`, and root `db/` as the live channel/application boundary.
- Keep `donna_runtime/` as the Agent SDK runtime boundary. It should not know transport details except the current bridge in `brain.py` and optional CLI `target_phone`.
- Either merge root `db/` and `backend/db/`, or make one an explicit adapter over the other. The current dual-model setup is the main architectural ambiguity.
- Treat `backend/memory/` as the memory service boundary. It should expose stable tool/hook APIs to `donna_runtime`, without leaking which DB package it uses.
- Treat `donna/attention/` as a proactive-feature harness until it is deliberately integrated into the live scheduler/runtime.
- Treat `dashboard/web/lib/plan.ts` as the frontend/backend contract for generated dashboard state.
