# Donna v2

WhatsApp-native personal AI. She/her. Thinking partner with persistent memory and a legible dashboard.

## Non-negotiables

- Single tool-use loop via Claude Agent SDK. No LangGraph. No Perceive-Act. No pre-computed situational briefs.
- Main model: Haiku 4.5. Sonnet only for specific upgrade cases. Opus only inside justified subagents.
- Living Profile lives in the cached system prompt. Never auto-reloaded mid-turn.
- Every capability is a tool. Every deterministic side-effect is a hook. Integrations via MCP.
- No chained LLM calls outside the BRAIN loop unless inside a declared subagent.

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
→ tools: retrieval | action | dashboard | terminators | subagent
→ hooks: PreToolUse guards | PostToolUse side-effects
→ Egress (WhatsApp out + memory writes)

Proactive triggers invoke the same loop with `mode="proactive"`.

## Tool categories

1. Retrieval — recall_*, read_*, list_*
2. Action — update_*, schedule_*, track, log_*
3. Dashboard — add_insight_card, flag_attention, update_living_profile
4. Terminators — send_burst, stay_silent, offer
5. Meta / subagent — dig_deeper, compile_brief, draft_high_stakes_message

Every tool description includes when-to-use AND when-NOT-to-use clauses.

## Memory layers (nine backends, all active)

1. Graphiti (entities + graph, FalkorDB)
2. Supermemory (episodic)
3. Supermemory (document chunks)
4. Procedural rules (Postgres, three tiers)
5. Observations (Postgres)
6. Open loops (Postgres)
7. User facts / Living Profile (Postgres JSONB)
8. Chat messages (Postgres)
9. Calendar (Postgres synced from Google)

## Directory layout

- `donna_runtime/` — BRAIN loop, tools, hooks, context builder
- `dashboard/` — Next.js web + design system
- `docs/` — specs and design docs
- `tests/` — pytest suite
- `archive/` — historical; DO NOT read or import from here
- `.port_sessions/` — session work product; DO NOT read from here

## Never do

- Never rebuild Perceive-Act.
- Never add LangGraph or LangChain.
- Never wrap the SDK in a second framework.
- Never pre-generate a situational brief before the loop.
- Never inject memory into context without a tool call.
- Never call Donna an "AI assistant."
- Never use em dashes in her voice.
- Never ship a tool without when-NOT-to-use in its description.
- Never merge without running evals.
- Never read or import from archive/.

## Cost discipline

Per-turn cost on Haiku with caching should be under $0.01 for reactive turns. If higher: wrong model, tool_search on small catalog, loop hitting max_turns, or bloated descriptions. Diagnose the cause.

## How to work here

When adding a tool:
1. Write the tool description first (when-to-use + when-NOT-to-use + schema)
2. Decide agency level (L0 / L1 / L2)
3. Decide render target (WhatsApp / dashboard / internal state)
4. Implement in donna_runtime/tools.py (or tool_logic.py for pure logic)
5. Add a unit test
6. Update primitives.md

When fixing a behavior:
1. Diagnose: tool-description problem, system-prompt problem, or missing-tool problem
2. Fix at the diagnosed layer. Do not add a pipeline stage.

When unsure: stop and ask. Do not invent framework abstractions.


## Cost discipline

Per-turn cost on Haiku with caching should be under $0.01 for reactive turns. If higher: wrong model, tool_search on small catalog, loop hitting max_turns, or bloated descriptions. Diagnose the cause.

## How to work here

When adding a tool:
1. Write the tool description first (when-to-use + when-NOT-to-use + schema)
2. Decide agency level (L0 / L1 / L2)
3. Decide render target (WhatsApp / dashboard / internal state)
4. Implement in donna_runtime/tools.py (or tool_logic.py for pure logic)
5. Add a unit test
6. Update primitives.md

When fixing a behavior:
1. Diagnose: tool-description problem, system-prompt problem, or missing-tool problem
2. Fix at the diagnosed layer. Do not add a pipeline stage.

When unsure: stop and ask. Do not invent framework abstractions.
EOF