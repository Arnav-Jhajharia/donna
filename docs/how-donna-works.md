# How Donna Works — The Whole Thing, Explained Simply

A ground-truth tour of the Donna v2 codebase as it exists on branch `phase-1-usable`. Written so a ten-year-old could follow, but with real file paths and line numbers so an engineer can jump straight to the code.

Companion to `CLAUDE.md` (which is the non-negotiables). This file is descriptive, not prescriptive: "what is" not "what should be."

> **Heads up — spec vs. code drift.** A few things CLAUDE.md promises are not yet built. Flagged inline with **GAP**.

---

## 1. Donna in one paragraph

Donna is a WhatsApp chat buddy with a memory. You send her a WhatsApp message. A small Python web server catches it, looks you up, wakes up her "brain," and her brain is literally Claude (the model) running in a loop. The only way the brain can *do* anything is by calling **tools** (little Python functions registered as an MCP server). The only way the brain can *end a turn* is by calling one special tool called `send_burst`, which is what actually ships the reply back to WhatsApp. After each turn, some background "hooks" quietly write what happened into nine different memory stores, so next time she remembers.

That's the whole thing. Everything else is plumbing around that sentence.

---

## 2. The picture

```
WhatsApp user
     │  (text, voice, image, doc)
     ▼
┌──────────────────────────────────────────────────────┐
│ api/main.py          ← FastAPI webhook               │
│  • parse_webhook                                      │
│  • dedupe, persist InboundMessage (replay-safe)      │
│  • _dispatch(phone) → task per phone number          │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ api/graph.py         ← ingress pipeline              │
│  • user_lookup (phone → user_id, create if new)      │
│  • enrich_state    (reply context, url excerpts)     │
│  • save user ChatMessage                             │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ donna_runtime/brain.py::donna_turn                   │
│  • resolve_session_id_db(user_id)   ← resume or new  │
│  • render_turn_context (local time, tz, reply, urls) │
│  • load_user_model_block (facts + brief for prompt)  │
│  • traced_donna_turn → runner._donna_turn_core       │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ donna_runtime/runner.py::_donna_turn_core            │
│  async for msg in query(prompt, options):            │
│      ← THIS is the brain loop (SDK-owned)            │
│  options come from options.py (model, tools, hooks)  │
│  prompt = wrap_user_message_with_context(...)        │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ Claude Agent SDK's query()                           │
│  • sends system_prompt + tools to model              │
│  • model picks tools; SDK runs PreToolUse hook       │
│  • SDK executes tool (MCP server), runs PostToolUse  │
│  • loop until model calls send_burst OR max_turns    │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ send_burst (terminator tool)                         │
│  • puts 1–3 messages into _OUTBOUND_BUFFER           │
│  • fires 4 memory hooks async                        │
│  • voice_filter cleans output                        │
└────────────────────┬─────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────┐
│ delivery/whatsapp.py::WhatsAppChannel.send_many      │
│  • render each OutboundMessage to WA API payload     │
│  • POST to graph.facebook.com                        │
│  • return wamids, tag assistant ChatMessage          │
└──────────────────────────────────────────────────────┘
```

---

## 3. Entry points (how messages arrive)

There are **three** ways a message enters Donna:

| # | Entry | File | Function | What it does |
|---|-------|------|----------|--------------|
| 1 | WhatsApp webhook (real users) | `api/main.py:418` | `webhook()` | Parses WA payload, dedupes (60s TTL), persists `InboundMessage`, dispatches per-phone task |
| 2 | Local CLI REPL (dev) | `chat_donna.py:109` | `repl()` | Types in terminal, calls `donna_turn()` directly |
| 3 | Raw SDK stream (test) | `stream_donna.py:44` | `main()` | One message, prints SDK output verbatim |

**Plus a proactive entry** (env-gated background job started inside the API process):
- `backend/memory/jobs/temporal_refresh.py` — every `DONNA_BRIEF_REFRESH_INTERVAL_S` seconds (default 7200), regenerates situation briefs. Spawned in `api/main.py` when `DONNA_BRIEF_REFRESH=1`.

**Plus a dedicated reminders service** (separate Railway deployment):
- `backend/memory/jobs/schedule_worker.py` — fires `DonnaSchedule` rows at their scheduled time, sends templated WhatsApp messages directly (no BRAIN re-entry), and appends each fired message to `chat_messages` with `is_proactive=True` so the next user-facing turn knows what Donna already said. Launched by `bin/start.sh` when `DONNA_PROCESS_ROLE=reminders`. Reminders no longer run inside the API process.

All five paths converge on the same function: `donna_runtime/brain.py::donna_turn`.

---

## 4. What's a "session"? (like you're 10)

Imagine Donna is a kid with a diary. Each time you talk, she writes the chat into a specific diary page. Next time, she flips back to that page and keeps going from where you left off. The "page number" is a **session_id** — a random ID like `83d9fa27-...`.

**Important facts about Donna's sessions:**

- The session lives **inside the Claude Agent SDK** (Anthropic's server), not on our disk. We only remember the ID.
- **One active session per user.** When you message Donna, she looks up *your* session_id and asks the SDK to "resume" that conversation.
- **Where the ID is stored:**
  - File (CLI): `.donna_sessions.json` — JSON map of `user_id → {session_id, updated_at}`.
  - DB (production): Postgres table `user_sessions` (`session_store.py:120` upserts it).
- **What counts as "this session":** the model's chat history. NOT the memory backends. Memory is separate.

### Session start

1. Message comes in → we resolve `user_id` (by phone or CLI arg).
2. `resolve_session_id_db(user_id)` — did we save an ID last time? (`brain.py:35`)
3. If yes → pass `resume=session_id` to `ClaudeAgentOptions` (`options.py:60`). SDK replays the old chat server-side.
4. If no → start fresh. SDK assigns a new `session_id` and returns it in the final `ResultMessage`.
5. When we get the new ID back, `save_user_session_db(user_id, session_id)` upserts it (`brain.py:88`).

### Session end

There is **no hard "end session" command**. A session dies only if:
- The model hits `max_turns` (default 6 reactive, 12 proactive) and the loop cuts off.
- We call with `fork_session=True` (unused in prod — creates a branch).
- We call with `new_session=True` (discards the old ID).
- The SDK times out server-side (Anthropic's policy, not ours).

**Per-turn end-of-turn actions** (every turn, always):
- Session ID saved back to DB.
- Turn trace appended to `donna_traces.jsonl`.
- User + assistant `ChatMessage` rows persisted.
- 4 memory hooks fire async (see §8).
- WhatsApp messages delivered via `delivery/whatsapp.py`.
- `InboundMessage.status = 'processed'`.

### The key insight

Message history = SDK session. Everything else about you (facts, open loops, observations, calendar, graph) = our nine memory backends. The system prompt carries a **snapshot** of who-you-are (Living Profile), so the model already knows you before the session history even kicks in. The per-turn volatile stuff (current time, timezone, URL previews) is prepended to **the user message**, not the system prompt — that keeps the system prompt stable so prompt-prefix cache stays warm (`runner.py:88-90`).

---

## 5. The brain loop

Donna does **not** have its own agent loop. The "loop" is a single `async for` over the SDK's `query()` generator:

```python
# donna_runtime/runner.py:92
async for message in query(prompt=wrapped_prompt, options=build_options(config)):
    _record_message(message, trace)
```

That's it. The SDK owns the turn-taking. We own:
- What goes into `options` (`options.py:35-65`).
- What's in the system prompt (`prompt.py:99-118`).
- The tools we register.
- The hooks that run before and after each tool call.
- What we do with each message the SDK streams back.

The loop terminates when:
- Model emits a `ResultMessage` (normal — it called `send_burst` and the subsequent turn said "done").
- `max_turns` hits (runaway).
- `TimeoutError` after `request_timeout_s` (default 45s) — caught at `runner.py:94`.

---

## 6. How tools are passed to the SDK (the exact plumbing)

This is the part people get confused about. Here is the full chain from "Python function" to "Claude can call it":

### Step 1 — decorate the function
Each tool is a Python async function wrapped in `@tool(name, description, input_schema)` from `claude_agent_sdk`:

```python
# donna_runtime/tools.py:76
@tool("read_tracker",
      "Read-only tracker lookup by observation type... Do NOT use for free-text recall...",
      {"type": "object", "required": ["name"], "properties": {...}})
@traceable(name="donna.tool.read_tracker", run_type="tool")
async def read_tracker(args):
    return await read_tracker_result(args)
```

The description must include **when-to-use AND when-NOT-to-use**. That's how we steer the model — the description *is* the policy.

### Step 2 — put it in the master tuple
All wrapped tools are collected in `DONNA_TOOLS` at `donna_runtime/tools.py:646-661`:

```python
DONNA_TOOLS = (
    recall_episodic, read_tracker, recall_graph, smart_recall,
    list_open_loops, list_calendar, log_observation, track_open_loop,
    close_open_loop, set_timezone, schedule_reminder,
    resolve_time_expression, read_situation_brief, send_burst,
)
```

A parallel `FAKE_DONNA_TOOLS` in `fake_tools.py` has canned stand-ins for tests and local dev (swap via `config.tool_mode = "fake"`).

### Step 3 — wrap into an MCP server
`options.py:26-32`:

```python
def build_mcp_server(config):
    return create_sdk_mcp_server(
        name="donna-tools", version="0.1.0",
        tools=_tools_for_mode(config.tool_mode),  # DONNA_TOOLS or FAKE_DONNA_TOOLS
    )
```

### Step 4 — pass into ClaudeAgentOptions
`options.py:40-64`:

```python
ClaudeAgentOptions(
    model=config.model,
    system_prompt=build_system_prompt(...),
    mcp_servers={"donna": build_mcp_server(config)},   # ← tools live here
    allowed_tools=[...],                               # whitelist (MCP names)
    disallowed_tools=[...],                            # blacklist
    hooks={
        "PreToolUse":  [HookMatcher(hooks=[pre_tool_hook])],
        "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
    },
    max_turns=config.max_turns,
    thinking="enabled" if config.thinking_enabled else "disabled",
    resume=config.resume_session_id,
    fork_session=config.fork_session,
)
```

### Step 5 — pass options to `query()`
`runner.py:92` → the SDK handles everything else. Tool names the model sees are `mcp__donna__<name>` (e.g. `mcp__donna__send_burst`).

### How the model picks a tool

It doesn't, technically. We give it:
- A system prompt that explains its role + voice + which tool buckets exist.
- A Living Profile (who you are).
- A bunch of tool schemas with explicit when-to / when-NOT-to clauses.

Then Claude decides. Our only enforcement is:
- `allowed_tools` / `disallowed_tools` at the SDK level (hard block).
- `pre_tool_hook` can **deny** a specific call at runtime (soft block with reason).

---

## 7. Tool catalog (what exists right now)

All real tools live in `backend/memory/tools/` (the logic) and are re-exported through `donna_runtime/tools.py` (the SDK decoration). There are **14 tools currently exposed to the model** and **several more defined but not wired**.

### Wired into the loop (in `DONNA_TOOLS`)

| # | Tool | Category | Purpose (plain english) | File |
|---|------|----------|-------------------------|------|
| 1 | `recall_episodic` | Retrieval | Search past chat snippets (dated memories) | `backend/memory/tools/recall_episodic.py` |
| 2 | `read_tracker` | Retrieval | Read counted events (expense, mood, sleep…) for a period | `donna_runtime/tool_logic.py` |
| 3 | `recall_graph` | Retrieval | Who-knows-whom facts from Graphiti/FalkorDB | `backend/memory/tools/recall_graph.py` |
| 4 | `smart_recall` | Retrieval | Let Donna pick: expand → fan out → rerank (RRF) | `backend/memory/tools/smart_recall.py` |
| 5 | `list_open_loops` | Retrieval | "What's still open?" pending threads | `backend/memory/tools/list_open_loops.py` |
| 6 | `list_calendar` | Retrieval | Upcoming 7 days from Google Calendar sync | `backend/memory/tools/list_calendar.py` |
| 7 | `read_situation_brief` | Retrieval | Raw stored situation brief (freshness check) | `backend/memory/tools/read_situation_brief.py` |
| 8 | `log_observation` | Action | Record a countable thing (meal, expense, mood) | `backend/memory/tools/log_observation.py` |
| 9 | `track_open_loop` | Action | Open a pending thread ("i should reply to mom") | `backend/memory/tools/track_open_loop.py` |
| 10 | `close_open_loop` | Action | Close a pending thread by loop_id | `backend/memory/tools/close_open_loop.py` |
| 11 | `set_timezone` | Action | Set IANA timezone, writes via bitemporal facts | `backend/memory/tools/set_timezone.py` |
| 12 | `schedule_reminder` | Action | Schedule one-shot reminder (fire_at OR in_minutes) | `backend/memory/tools/schedule_reminder.py` |
| 13 | `resolve_time_expression` | Action | Parse "last tuesday" → UTC ISO timestamp | `backend/memory/tools/resolve_time_expression.py` |
| 14 | `send_burst` | Terminator | **The only way to end a turn.** 1–3 WA messages out | `donna_runtime/tools.py:626` |

### Defined but NOT wired into `DONNA_TOOLS` (GAPs)

| Tool | Category | Where it lives | Status |
|------|----------|----------------|--------|
| `list_observations` | Retrieval | only in `fake_tools.py` | **Fake-only** |
| `list_rules` | Retrieval | `backend/memory/tools/list_rules.py` | **Not wired** |
| `recall_document_chunks` | Retrieval | `backend/memory/tools/recall_document_chunks.py` | **Not wired** |
| `recall_chat_thread` | Retrieval | `backend/memory/tools/recall_chat_thread.py` | **Not wired** (cold-start injection path) |
| `refresh_situation_brief` | Action | `backend/memory/tools/refresh_situation_brief.py` | **Auto-fires only** (not model-facing) |
| `update_living_profile` | Action | `backend/memory/tools/update_living_profile.py` | **Not wired** |

### Declared in CLAUDE.md but NOT implemented anywhere

| Tool | Category | Status |
|------|----------|--------|
| `stay_silent`, `offer` | Terminators | **MISSING** — only `send_burst` exists |
| `add_insight_card`, `flag_attention` | Dashboard | **MISSING** — entire Dashboard category is 0 tools |
| `dig_deeper`, `compile_brief`, `draft_high_stakes_message` | Meta / subagent | **MISSING** |

**Coverage:** 8 retrieval / 5 action / 0 dashboard / 1 terminator / 0 meta currently exposed to the model.

---

## 8. Hooks and gates (the quiet machinery)

CLAUDE.md rule: "Every deterministic side-effect is a hook." Two hook layers:

### Layer A — SDK hooks (run around every tool call)

Registered in `options.py:55-58`. Defined in `donna_runtime/hooks.py`.

- **`pre_tool_hook`** (`hooks.py:84-150`)
  - **Double-terminator guard:** second `send_burst` in one turn → DENY.
  - **Idempotency guard:** duplicate `log_observation` / `track_open_loop` / `schedule_reminder` with identical args → DENY (SHA256 of input).
  - Records `tool.call` observability event.
- **`post_tool_hook`** (`hooks.py:153-160`)
  - Records hook completion.
  - Delegates to LangSmith trace (if enabled).

### Layer B — memory hooks (run only after `send_burst`)

Defined in `backend/memory/hooks/__init__.py::ALL_HOOKS`. Fired as 4 parallel async tasks by `post_tool_hook` when terminator is detected:

| Hook | What it writes | Gated? |
|------|----------------|--------|
| `save_chat_messages.py` | `chat_messages` rows (user + assistant) | No (idempotent flag check) |
| `record_episode.py` | Supermemory episode ("USER: ... DONNA: ...") | No |
| `ingest_to_graph.py` | Graphiti/FalkorDB episode | **Yes — see gate below** |
| `extract_user_facts.py` | Structured facts via Haiku + language detect | No |

### Gate — `graph_ingest_gate.py`

Three-layer decision before graph ingestion:

1. **Fast reject** (`_fast_reject`): inbound <20 chars, or ambient-filler token ("k", "lol", "ok", "thanks", …).
2. **Fast accept** (`_fast_accept`): multi-message burst (outbound ≥2), OR a recall tool was called this turn.
3. **Haiku judgment**: structured call returning `{worth_ingesting, reason}`. Defaults to reject if Haiku unavailable.

Every verdict is logged to `donna_gate.jsonl` (path in `settings.gate_log_path`). Fields: `ts, key, inbound_len, n_outbound, tools, terminator, verdict, reason, layer`.

---

## 9. Observability

Two JSONL streams + optional LangSmith. Everything is schema-versioned.

### `donna_traces.jsonl` — one record per turn
Written by `TurnTrace.persist()` at `donna_runtime/tracing.py:252`. Contains: `turn_id, user_message, started_at, duration_ms, num_turns, session_id, resume_session_id, tool_calls[], tool_results[], hook_events[], model_thoughts[], usage, cost_usd, cache_*_tokens, result_subtype`.

### `donna_gate.jsonl` — one record per gate decision
Written by `graph_ingest_gate.py`.

### `.donna/events.jsonl` — structured event stream
Written by `donna_runtime/observability.py`. Event types:
- `turn.start` / `turn.end`
- `tool.call` / `hook.deny`
- `memory.op` (decorator-emitted around memory client calls)
- `retry.fired` / `error`

Env knobs: `DONNA_OBS_LOG`, `DONNA_OBS_STDOUT`, `DONNA_OBS_DISABLED`.

### LangSmith (optional)
`donna_runtime/langsmith_tracing.py` — no-op if package not installed. Every tool function is also `@traceable`.

### Audit (post-hoc, not live)
`donna_runtime/audit.py::audit_trace` scans a trace JSONL for policy violations: disallowed tools used, missing terminator, `send_burst` violations (too many items, too long, em dashes, uppercase). Not a side-effect system — a read-only report.

### Health
`donna_runtime/health.py::run_health_checks` — CLI-invoked sanity check (SDK installed, CLI on PATH, `ANTHROPIC_API_KEY` set, filesystem writable). No HTTP endpoint.

---

## 10. The system prompt (what Donna "knows by default")

Built once per turn in `donna_runtime/prompt.py::build_system_prompt` and cached by the SDK. Assembly order:

1. **`_DONNA_CORE`** (`prompt.py:31-55`) — identity, voice rules, safety floors.
2. **`_TERMINATOR_CONTRACT`** (`prompt.py:58-65`) — "every turn ends with send_burst" + WhatsApp widget catalog (from `delivery/whatsapp.py::CAPABILITIES_PROMPT`).
3. **`_STAGE_0_5_TAIL`** (`prompt.py:78-84`) — "memory and action tools available via MCP; trust their descriptions."
4. **Living Profile block** (if present) — injected under `# WHO YOU'RE TALKING TO`.

**Per-turn volatile context** is NOT here. It's prepended to the *user message* via `wrap_user_message_with_context()` (`prompt.py:121-131`). That's what keeps the cache warm.

---

## 11. The nine memory backends

| # | Layer | Backend | Read via | Write via |
|---|-------|---------|----------|-----------|
| 1 | Graph (entities, relations) | Graphiti + FalkorDB (`backend/memory/clients/graphiti.py`) | `recall_graph`, `smart_recall` | `ingest_to_graph` hook (gated) |
| 2 | Episodic | Supermemory (`clients/supermemory.py`) | `recall_episodic`, `smart_recall` | `record_episode` hook |
| 3 | Document chunks | Supermemory (doc index) | `recall_document_chunks` (**not wired**) | document upload pipeline |
| 4 | Procedural rules (3 tiers) | Postgres `procedural_rules` | `list_rules` (**not wired**) | `extract_user_facts` hook |
| 5 | Observations (tracker data) | Postgres `observations` | `read_tracker`, `list_observations` (fake only) | `log_observation` tool |
| 6 | Open loops | Postgres `open_loops` | `list_open_loops` | `track_open_loop` / `close_open_loop` |
| 7 | User facts + Living Profile | Postgres `users.facts` / `users.living_profile` (JSONB) | **injected into system prompt** | `extract_user_facts` hook; `update_living_profile` tool (**not wired**); nightly `synthesize_nightly_profile` (**no scheduler**) |
| 8 | Chat messages | Postgres `chat_messages` | `recall_chat_thread` (**not wired**; cold-start only) | `save_chat_messages` hook |
| 9 | Calendar | Postgres `calendar_entries` (Google Calendar sync) | `list_calendar` | external Composio pipeline |

### How they compose

`smart_recall` is the "I don't know which source" facade. Pipeline at `backend/memory/retrieval/pipeline.py`:
1. **Expand** (Haiku rewrites query + facets).
2. **Fanout** (parallel hits to Supermemory + Graphiti).
3. **Attention boost** (optional re-rank; **not yet wired** — see §13).
4. **Rerank** (RRF merge → top K).

`retrieval/` = pull path (on-demand). `synthesis/` = push path (nightly, living profile + temporal brief). The synthesis path exists but has **no scheduler wired**.

### Living Profile (important caveat)

Per CLAUDE.md, Living Profile lives in the cached system prompt, never auto-reloaded mid-turn. In code right now:
- The *shape* exists: Pydantic `_Profile` in `backend/memory/synthesis/living_profile.py:37-43`.
- The *synthesis function* exists: `synthesize_nightly_profile()` — Haiku-driven, 4 search angles, writes to `users.living_profile` JSONB.
- The *per-user load* partially works: `load_user_model_block()` in `context_builder.py`, but currently **hard-coded to the `LIVING_PROFILE` constant in `donna_runtime/data.py`** (hand-authored for the test user Arnav).
- The *targeted patch tool* (`update_living_profile`) exists but is **not wired into `DONNA_TOOLS`**.
- The *nightly scheduler* that would call `synthesize_nightly_profile` is **not wired** anywhere.

**GAP:** production-ready Living Profile requires (a) hook that loads from DB at session start, (b) scheduler for nightly synthesis, (c) wire `update_living_profile` tool.

---

## 12. Voice & thinking

- **Voice filter** (`donna_runtime/voice_filter.py`): applied to every text item in `send_burst` output. Enforces: lowercase, no em dashes, no semicolons, no banned phrases ("i understand", "great question", "ai assistant", "i'm here to help"). Violations are logged (not silently dropped) so evals can catch regressions.
- **Thinking triage** (`donna_runtime/thinking_triage.py::should_think`): heuristic that flips `config.thinking_enabled` per turn. Enabled on: safety keywords, decisions, replies, fetched URLs, substantive questions, first-message. Disabled on: empty, ambient chatter (<25 chars, no "?").
- **Awareness judge** (`donna_runtime/awareness_judge.py`): eval-time check that flags off-policy tool calls (e.g., calling `log_observation` on "k" / ambient).

---

## 13. Subagents (what CLAUDE.md promises vs. what exists)

| Promised | Implemented? |
|----------|--------------|
| `dig_deeper` | **No** |
| `compile_brief` | **No** |
| `draft_high_stakes_message` | **No** |

What **does** use a subagent-like pattern:
- `extract_user_facts` hook → calls Haiku via `call_structured()` to pull canonical facts.
- `graph_ingest_gate` layer 3 → Haiku judge on whether a turn is worth graphing.
- `backend/memory/synthesis/living_profile.py::synthesize_nightly_profile` → Haiku synthesis (nightly, when scheduler exists).
- `donna/attention/author.py` → Haiku authors an `AttentionSpec` given a normalized intent.

**None of these are exposed as model-facing tools.** They're internal.

### Attention subsystem (status)

Per saved memory: `donna/attention/` was completed 2026-04-21 but is **not wired into `brain.py`**. It has its own schema (`AttentionSpec`, card types like EventStream/Tally/Brief/PrepDoc/OpenLoop/Ping), a harness (`intent → normalize → retrieve → author → validate → dry_run`), a scheduler (`scheduler.py`), and a promote path (SHADOW→LIVE). `backend/memory/retrieval/pipeline.py:69-70` already supports an `active_attentions` argument in `apply_attention_boost()`, but `brain.py` never populates it.

**To wire it in**: (a) load active attentions per user at turn start, (b) thread them into `run_retrieval()`, (c) expose a tool like `create_attention` or `set_attention_status`, (d) run `scheduler.py` as a background task and have it call `donna_turn` in proactive mode.

---

## 14. DB tables at a glance

From `db/models.py` (16 tables). Short purpose per table:

| Table | Purpose |
|-------|---------|
| `users` | Identity, phone, tz, flags, `facts` JSONB, `living_profile` JSONB |
| `chat_messages` | Conversation history |
| `procedural_rules` | Learned if-then behaviors |
| `observations` | Time-series events (meal, mood, expense, sleep…) |
| `schema_registry` | Per-user census of observation types |
| `open_loops` | Pending threads |
| `facts` | Bi-temporal fact store (t_valid, t_recorded, supersession) |
| `calendar_entries` | Google Calendar sync |
| `documents` | WhatsApp doc uploads (→ Supermemory) |
| `donna_schedule` | Reminders & scheduled proactive messages |
| `donna_instances` | Ambient feature instances (stub) |
| `run_trace` | Execution traces |
| `oauth_tokens` | Google/GitHub OAuth |
| `inbound_messages` | Raw WA inbound (replay-safe) |
| `user_sessions` | SDK session_id per user |

---

## 15. One concrete turn, end to end

Say user Alice (phone +65…) texts "logged coffee 6 bucks".

1. Meta POSTs to `/webhook`. `api/main.py:418::webhook` parses, dedupes, inserts `InboundMessage`, spawns a task for Alice's phone.
2. `_run_pipeline` merges any batched messages. `user_lookup` resolves phone → `user_id = abc-123`.
3. `enrich_state` adds reply context + url excerpts. `_save_user_message` writes a `chat_messages` row.
4. `donna_turn(state, config)` at `brain.py:24`:
   - `resolve_session_id_db("abc-123")` → returns last session_id, say `sess-xyz`.
   - `render_turn_context(state)` → string with local time, tz confirmed flag, recent chat, urls.
   - `load_user_model_block("abc-123")` → Living Profile + situation brief text.
   - Calls `traced_donna_turn` → `_donna_turn_core` at `runner.py:58`.
5. `build_options()` constructs `ClaudeAgentOptions` with Sonnet 4.6, MCP server, allowed tools, hooks, `resume=sess-xyz`, `max_turns=6`, thinking on/off per triage.
6. `async for message in query(wrapped_prompt, options)`:
   - Claude thinks: "this is a countable expense."
   - Claude calls `mcp__donna__log_observation(type="expense", fields={amount_cents: 600, ...})`.
   - `pre_tool_hook` → idempotency check passes → emits `tool.call` event → allows.
   - SDK runs the tool. `log_observation_result()` writes to `observations` table. Returns `{status: "logged", id: 42}`.
   - `post_tool_hook` → records, delegates to LangSmith.
   - Claude thinks: "ack the user, terminate."
   - Claude calls `mcp__donna__send_burst(messages=[{text: "coffee 6 logged. going up this week — want the trend?"}])`.
   - `pre_tool_hook` → first `send_burst` → allows.
   - `send_burst_result()` runs voice filter, pushes to `_OUTBOUND_BUFFER`.
   - `post_tool_hook` → fires 4 memory hooks async: `save_chat_messages`, `record_episode`, `ingest_to_graph` (gate: fast_accept because a memory tool fired this turn), `extract_user_facts`.
   - SDK sends a `ResultMessage` with `session_id=sess-xyz`, cost, usage.
7. Loop ends. `runner.py:102-110`: emits `turn.end` event, saves session id, delivers buffered messages via `WhatsAppChannel.send_many`.
8. `TurnTrace.persist()` → one line appended to `donna_traces.jsonl`.
9. `mark_processed(row_ids)` on `InboundMessage`.

Total cost on Sonnet 4.6 with caching: ~$0.007 for a turn like this. Reactive turn budget per CLAUDE.md is <$0.01 on Haiku — we're currently slightly above because the code runs Sonnet 4.6 (see §16).

---

## 16. Known spec-vs-code drift

Things CLAUDE.md or primitives.md imply but code doesn't match:

1. **Model.** CLAUDE.md says "Main model: Haiku 4.5." `donna_runtime/config.py:10-12` sets `MODEL_NAME = "claude-sonnet-4-6"`. Either the spec is stale or the config is. Sonnet ≈ 6× cost of Haiku at parity tokens — affects cost-discipline target.
2. **Dashboard tools.** `add_insight_card`, `flag_attention`, `update_living_profile` (dashboard variant) — **none implemented**.
3. **Extra terminators.** `stay_silent`, `offer` — **not implemented**. Only `send_burst` terminates.
4. **Meta/subagent tools.** `dig_deeper`, `compile_brief`, `draft_high_stakes_message` — **not implemented**.
5. **Living Profile hot-load.** Currently hard-coded to the `LIVING_PROFILE` string constant in `donna_runtime/data.py`. Not per-user in production.
6. **Nightly synthesis.** `synthesize_nightly_profile` exists; **no scheduler calls it**.
7. **Attention subsystem.** Fully built under `donna/attention/`; **not wired into the brain loop**.
8. **Situation-brief temporal pipeline.** `backend/memory/synthesis/temporal_brief.py` exists; not called by any scheduler.
9. **`list_rules`, `recall_document_chunks`, `update_living_profile`, `recall_chat_thread`** — exist as functions, not in `DONNA_TOOLS`.
10. **DonnaInstance table** in DB has **no reader/writer code** — stub.

---

## 17. Where to add new stuff (surface-area map)

If you're adding a new…

- **Retrieval tool** → new file in `backend/memory/tools/`, logic there, decorator wrapper + export in `donna_runtime/tools.py`, append to `DONNA_TOOLS`, add to `allowed_tools` in `donna_runtime/config.py`, write a unit test, update `primitives.md`. Include when-to and when-NOT-to in the description — the PreToolUse hook does not enforce this, the description does.
- **Action tool** (writes state) → same as above, plus add to `_IDEMPOTENCY_GUARDED_TOOLS` in `hooks.py` if duplicates within a turn should be blocked. Decide the agency level (L0/L1/L2).
- **Dashboard tool** → same plumbing; just remember to pick a render target (probably `.donna/events.jsonl` or a new DB write that the Next.js dashboard reads).
- **Terminator** → same plumbing, but double-terminator guard in `pre_tool_hook` currently only knows `send_burst`. Generalize that check.
- **Meta / subagent tool** → add the tool, but it should spawn a subagent (another SDK query with its own options, typically Opus and its own mini-toolset). Keep it inside the tool handler — never chain LLM calls outside the BRAIN loop.
- **New memory backend** → client in `backend/memory/clients/`, retrieval integration in `backend/memory/retrieval/pipeline.py` (add a source to the fanout), gate decision if writes are expensive, tool wrapper for model-facing reads, hook for writes on `send_burst`.
- **New hook** → function in `backend/memory/hooks/` returning `None`, append to `ALL_HOOKS` in `backend/memory/hooks/__init__.py`. It will fire automatically after `send_burst`.
- **New entry point** → normalize to the same `donna_turn(state, config)` call. Don't bypass the brain loop.

**Don't**: add a pipeline stage to "fix a behavior" — CLAUDE.md rule is to fix at tool-description / system-prompt / missing-tool level. Don't re-introduce Perceive-Act. Don't wrap the SDK in another framework.

---

## 18. Cheat sheet

- **Turn entry:** `donna_runtime/brain.py::donna_turn`
- **Loop body:** `donna_runtime/runner.py::_donna_turn_core` → `async for message in query(...)`
- **Tool tuple:** `donna_runtime/tools.py::DONNA_TOOLS`
- **Tool logic:** `backend/memory/tools/*.py`
- **Options:** `donna_runtime/options.py::build_options`
- **System prompt:** `donna_runtime/prompt.py::build_system_prompt`
- **Hooks (SDK):** `donna_runtime/hooks.py`
- **Hooks (memory):** `backend/memory/hooks/__init__.py::ALL_HOOKS`
- **Gate:** `backend/memory/gates/graph_ingest_gate.py`
- **Traces:** `donna_traces.jsonl`, `donna_gate.jsonl`, `.donna/events.jsonl`
- **Session store:** `donna_runtime/session_store.py`, `.donna_sessions.json` (file), `user_sessions` (DB)
- **Deliver WA:** `delivery/whatsapp.py::WhatsAppChannel.send_many`
- **Attention (orphan):** `donna/attention/*`
- **DB tables:** `db/models.py`

Done. Go break something.
