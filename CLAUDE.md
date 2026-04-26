# Donna v2

WhatsApp-native personal AI. She/her. Thinking partner with persistent memory and a legible dashboard.

## Non-negotiables

- Single tool-use loop via Claude Agent SDK. No LangGraph. No Perceive-Act. No pre-computed situational briefs.
- Main model: Sonnet 4.6 across all slots (reactive, proactive, upgrade). Haiku 4.5 only for offline eval/awareness scoring. Opus only inside justified subagents.
- Living Profile is rendered into the system prompt at the start of every turn from `backend.memory.user_facts.rendering.load_and_render`. It is not auto-reloaded mid-turn.
- Every capability is a tool. Every deterministic side-effect is a hook. Integrations via MCP.
- LLM calls outside the BRAIN loop are only allowed in (a) declared subagents or (b) async post-turn hooks (e.g. user-facts extraction). Anything else is drift — flag it.

## Voice

- She/her pronouns. Always.
- Lowercase register. No em dashes. No semicolons.
- Blunt. High-agency. No filler.
- Never "I understand" or "Great question."
- When the user is anxious: acknowledge briefly, then be useful. Do not perform empathy.
- When the user is wrong: say so.
- When she does not know: say so. Do not fabricate.

## Architecture (layered)

WhatsApp inbound → Ingress (deterministic)
→ BRAIN loop (SDK tool-use loop)
→ tools: retrieval | action | dashboard | terminators | meta | web | media
→ hooks: PreToolUse guards | PostToolUse side-effects
→ Egress (WhatsApp out + memory writes)

Proactive triggers invoke the same loop with `mode="proactive"`.

## Tool categories

1. Retrieval — `recall`, `recall_episodic`, `recall_graph`, `read_tracker`, `read_situation_brief`, `list_open_loops`, `list_calendar`, `check_calendar`
2. Action — `log_observation`, `track_open_loop`, `close_open_loop`, `schedule_reminder`, `schedule`, `remember`, `set_timezone`, `resolve_time_expression`, `watch`
3. Terminators — `send_burst`, `stay_silent`, `offer`
4. Meta / subagent — `dig_deeper`, `compile_brief`, `draft_high_stakes_message`
5. Web / research — `web_search`, `agentic_web_search`, `research`
6. Media — `image`, voice (`voice_synth`, `voice_intent`)

Every tool description must include when-to-use AND when-NOT-to-use clauses. Audit periodically — drift here is silent.

## Memory layers

Active backends:

1. Graphiti (entities + graph, FalkorDB)
2. Supermemory (episodic)
3. Supermemory (document chunks)
4. Procedural rules (Postgres, three tiers)
5. Observations (Postgres)
6. Open loops (Postgres)
7. User facts / Living Profile (Postgres JSONB)
8. Chat messages (Postgres)
9. Calendar (Postgres synced from Google)
10. Web (Exa-backed search + research pipeline)

Unified read surface: `recall(query, purpose=auto)` fans out across observations, open_loops, Graphiti, and Supermemory episodic with RRF rerank. Use `purpose=observations|open_loops|situation_brief` to force a lane. Use specific `recall_*` only when the backend matters.

Unified write surface: `remember(kind=observation|open_loop|...)`. Profile facts and preferences are off-limits to `remember` — those are written by the post-turn extractor hook.

## Directory layout

- `donna_runtime/` — BRAIN loop, tools, hooks, context builder, prompt assembly
- `donna/` — subsystems (e.g. `attention/`)
- `backend/` — memory backends, retrieval pipeline, synthesis jobs, web pipeline
- `db/` — SQLAlchemy models and migrations
- `ingress/` — WhatsApp inbound + deterministic preprocessing
- `delivery/` — WhatsApp outbound, message formatting
- `api/` — HTTP surface
- `dashboard/` — Next.js web + design system
- `donna-design-system/` — design tokens / shared primitives
- `docs/` — specs and design docs
- `scripts/` — operational scripts
- `tests/` — pytest suite

## Never do

- Never rebuild Perceive-Act.
- Never add LangGraph or LangChain.
- Never wrap the SDK in a second framework.
- Never pre-generate a situational brief before the loop.
- Never inject memory into context without a tool call (the only exceptions are USER MODEL, SITUATION BRIEF, TODAY block, and RECENT CHAT — all assembled by the context builder).
- Never call Donna an "AI assistant."
- Never use em dashes in her voice.
- Never ship a tool without when-NOT-to-use in its description.
- Never merge without running evals.

## Cost discipline

Per-turn cost on Sonnet 4.6 with prompt caching should stay in the low single-digit cents for reactive turns. If higher: bloated context (oversized USER MODEL, RECENT CHAT too long), loop hitting max_turns, redundant tool calls, or `recall` being invoked when USER MODEL/SITUATION BRIEF already had the answer. Diagnose the cause; do not paper over with a smaller model.

## How to work here

When adding a tool:
1. Write the tool description first (when-to-use + when-NOT-to-use + schema)
2. Decide agency level (L0 / L1 / L2)
3. Decide render target (WhatsApp / dashboard / internal state)
4. Implement in `donna_runtime/tools.py` (or `tool_logic.py` for pure logic)
5. Add a unit test
6. Update `primitives.md`

When fixing a behavior:
1. Diagnose: tool-description problem, system-prompt problem, or missing-tool problem
2. Fix at the diagnosed layer. Do not add a pipeline stage.

When unsure: stop and ask. Do not invent framework abstractions.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
