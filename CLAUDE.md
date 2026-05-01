# Donna v2

WhatsApp-native personal AI. She/her. **The AI that feels human.**

Donna is a presence, not an assistant. Her job is to hold your life — what's going on, what you said, what you're meant to do, what you're tracking — and never let anything slip. You text her like you'd text a friend. You point things off to her. She remembers. She follows up. She tracks your habits, your health, the people who matter. She has awareness of where you are and what's coming.

The dashboard is where she does amazing things with the stuff she's holding for you — the editorial view of your day, your moments, your trackers, the things she noticed that you didn't.

## What Donna is

- A presence with memory. The continuity is the product.
- A second brain that reaches out, not just one you query.
- An assistant in the practical sense (reminders, tracking, follow-ups), but in a register that feels human, not transactional.
- A WhatsApp companion first. The dashboard is the canvas she paints on, not the place where she lives.

## What Donna is not

- A thinking partner who debates you. Not the framing.
- A productivity tool. She doesn't draft documents, run your CRM, or replace your EA's iPad.
- A therapist. She has a soft register and asks reflective questions, but she is not clinical and must not be relied on as one.
- An "AI assistant." Never use that phrase.

## Non-negotiables

- Single tool-use loop via Claude Agent SDK. No LangGraph. No Perceive-Act. No pre-computed situational briefs.
- Main model: Sonnet 4.6 across all reactive/proactive BRAIN turns and the dashboard composer. Haiku 4.5 is used inside specific declared lanes (post-turn user-facts extractor, Tier 2 proactive judge, awareness scoring, image captioning). Opus only inside justified subagents.
- Living Profile is rendered into the wrapped user prompt at the start of every turn by `donna_runtime.context_builder` (USER MODEL block + SITUATION BRIEF + TODAY block + RECENT CHAT). It is not auto-reloaded mid-turn.
- Every capability is a tool. Every deterministic side-effect is a hook. External integrations via Composio.
- LLM calls outside the BRAIN loop are only allowed in (a) declared subagents or (b) async post-turn hooks (e.g. user-facts extraction, dispatcher Tier 2 judge). Anything else is drift — flag it.

## Reliability is the brand

Because Donna's promise is "she holds your life," every silent failure is brand-damaging in a way it would not be for a tool product. A reminder that doesn't fire is not a bug — it's a betrayal. A voice note not indexed is not a missing feature — it's her not having heard you. Reliability gates everything else.

Operating principles that follow:
- A `DonnaSchedule` row that hasn't fired by `fire_at + 60s` is an alert.
- Synthesis jobs that haven't run for an active user in >24h are an alert.
- Missing voice / photo content from the searchable memory index is a regression.
- Day 1 must always work end-to-end, not "should work after the user texts again."

## Voice

- She/her pronouns. Always.
- Lowercase register. No em dashes. No semicolons.
- Blunt. High-agency. No filler.
- Never "I understand" or "Great question."
- When the user is anxious: acknowledge briefly, then be useful. Do not perform empathy.
- When the user is wrong: say so.
- When she does not know: say so. Do not fabricate.
- Confrontation flavor exists for a reason — but never use it on a user who reads as fragile or in crisis. Soften and route.

## Architecture (layered)

WhatsApp inbound → Ingress (deterministic)
→ BRAIN loop (SDK tool-use loop)
→ tools: retrieval | action | dashboard | terminators | meta | web | media
→ hooks: PreToolUse guards | PostToolUse side-effects
→ Egress (WhatsApp out + memory writes)

Proactive triggers invoke the same loop with `mode="proactive"`.

## Tool categories

1. Retrieval — `recall`, `recall_episodic`, `recall_graph`, `read_tracker`, `read_situation_brief`, `list_open_loops`, `list_calendar`, `check_calendar`
2. Action — `log_observation`, `track_open_loop`, `close_open_loop`, `schedule_reminder`, `attend`, `cancel_attention`, `snooze_attention`, `remember`, `set_timezone`, `resolve_time_expression`
3. Terminators — `send_burst` (the only true terminator today; CLAUDE.md previously listed `stay_silent` and `offer` but those are not in the code)
4. Meta / subagent — declared per feature; the previously-listed `dig_deeper` and `compile_brief` are not yet implemented and the `research` tool runs inline in the BRAIN loop today
5. Web / research — `web_search`, `agentic_web_search`, `research`
6. Media — `image`, voice (`voice_synth`, `voice_intent`), document ingest (PDF, image, voice STT)

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
11. Bitemporal facts (Postgres) — built but currently unused; ship readers or delete.

Unified read surface: `recall(query, purpose=auto)` fans out across observations, open_loops, Graphiti, Supermemory episodic, and the situation brief with RRF rerank. **Calendar, document chunks, procedural rules, and bitemporal facts are NOT yet in the fanout** — they're behind separate tools. Closing this is on the roadmap; until it does, a "what did I tell Donna about Maya last month" query has known coverage gaps.

Unified write surface: `remember(kind=observation|open_loop|...)`. Profile facts and preferences are off-limits to `remember` — those are written by the post-turn extractor hook.

## What Donna must hold reliably

These are the surfaces where "she holds your life" must work or the product fails:

- **Reminders** — both user-set ("remind me at 6") and system-spawned ("hydration check next morning"). Fire on time, in the user's timezone, with the right message.
- **Open loops** — anything the user said they'd do. Never silently drop. Re-surface with age in the user's voice.
- **Trackers** — habits and health, longitudinal. Streaks, drift, narrative-over-time.
- **People** — names + dynamics. Last touch. What's pending between us.
- **Voice notes** — must be transcribed AND chunked into searchable memory, not stored as opaque audio.
- **Photos** — must be captioned AND indexed. Visual reference must be recallable.
- **Documents** — PDFs and Drive content must be chunked, embedded, recallable.

If any of these holds is silent or partial, that's the bug to fix before anything new is added.

## Directory layout

- `donna_runtime/` — BRAIN loop, tools, hooks, context builder, prompt assembly
- `donna/` — subsystems (e.g. `attention/`)
- `backend/` — memory backends, retrieval pipeline, synthesis jobs, web pipeline, integrations, dashboard composer
- `db/` — SQLAlchemy models and migrations
- `ingress/` — WhatsApp inbound + deterministic preprocessing + STT
- `delivery/` — WhatsApp outbound, message formatting
- `api/` — HTTP surface (api routes, webhooks)
- `proactive/` — Tier 1/2 dispatcher, judge, sources, spawners
- `dashboard/` — Next.js web + design system + 21-archetype catalogue
- `donna-design-system/` — design tokens / shared primitives
- `donna-voice/` — separate package for live voice calls (LiveKit + SIP)
- `docs/` — specs and design docs
- `audit/` — system-by-system honest assessments
- `scripts/` — operational scripts (workers, cleanup, evals)
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
- Never let a `DonnaSchedule` row miss its fire and silently move on without alerting.
- Never claim "she holds X" if the read surface or storage doesn't actually fuse X.
- Never ship hardening on confrontation/reflection without a register-detection / safety route for vulnerable users.

## Cost discipline

Per-turn cost on Sonnet 4.6 with prompt caching should stay in the low single-digit cents for reactive turns. If higher: bloated context (oversized USER MODEL, RECENT CHAT too long), loop hitting max_turns, redundant tool calls, or `recall` being invoked when USER MODEL/SITUATION BRIEF already had the answer. Diagnose the cause; do not paper over with a smaller model.

For proactive fires: the dispatcher Tier 2 judge (Haiku 4.5) is the cheap path; the BRAIN re-entry path is for cases that need tools or judgment. Today the dispatcher runs in mirror mode (`DONNA_PROACTIVE_TIERED` unset) and every fire pays the BRAIN cost. Flipping to gated mode is a planned step once the cooldown table backfill lands.

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

## Production topology (as of 2026-04-28)

Five Railway services on the `abundant-vision` project, all on the `phase-1-usable` branch:

- `donna` — api + webhook + dashboard backend (uvicorn)
- `donna-attention` — proposer/promoter loop (`scripts/run_attention_worker.py`)
- `donna-synthesis` — Living Profile synthesis + morning trigger (`scripts/run_synthesis_worker.py`)
- `donna-reminders` — schedule worker, fires DonnaSchedule rows (`scripts/run_schedule_worker.py`)
- `FalkorDB` — graph backend

Plus `zealous-perception` (empty stub, can delete).

Branch reality: `phase-1-usable` is what runs in prod. `main` was broken since 2026-04-25 due to a missing import; the fix landed on `phase-1-usable` in commit `1f454ef` and the working tree was unblocked in `3349747`. Either merge `phase-1-usable` to `main` or retarget docs to recognize `phase-1-usable` as the stable branch.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
