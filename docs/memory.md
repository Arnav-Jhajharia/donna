# Memory

Donna's memory is a nine-layer system split across Postgres, Supermemory, and
Graphiti (FalkorDB). This doc maps the surface: what each layer holds, which
tools read/write it, and how ingestion is gated.

## Nine layers

| # | Layer | Store | Purpose |
|---|-------|-------|---------|
| 1 | Living Profile | `users.living_profile` JSONB | Nightly-synthesized situational brief |
| 2 | Canonical user facts | `users.facts` JSONB | Preferences, profession, city, etc. |
| 3 | Episodic memory | Supermemory | Per-turn narrative snippets |
| 4 | Knowledge graph | Graphiti / FalkorDB | Relational facts (people, decisions) |
| 5 | Document chunks | Supermemory | Uploaded documents, indexed chunks |
| 6 | Chat messages | `chat_messages` | Verbatim turn log |
| 7 | Observations | `observations` | Trackers, mood, expenses, habits |
| 8 | Open loops | `open_loops` | Unresolved threads awaiting follow-up |
| 9 | Procedural rules | `procedural_rules` | Tier-1 (explicit) + Tier-2 (inferred) behavior |

## Tool surface (spec §5)

Read tools: `recall_episodic`, `recall_graph`, `recall_document_chunks`,
`recall_chat_thread`, `list_observations`, `list_open_loops`, `list_rules`,
`list_calendar`, `smart_recall`.

Write tools: `log_observation`, `track_open_loop`, `close_open_loop`,
`update_living_profile`.

Every tool returns `{status: ok | no_hits | degraded, payload: ...}` —
degraded means a backing service is unavailable; callers should fall through
rather than retry.

## Hooks (spec §6)

After every `send_burst` the runtime fans out four PostToolUse hooks, each
wrapped in `asyncio.create_task` so none blocks response delivery:

1. `save_chat_messages` — persists inbound + outbound to `chat_messages`
2. `record_episode` — unconditional Supermemory write
3. `ingest_to_graph` — gated by the selectivity gate (§7)
4. `extract_user_facts` — Haiku subagent + language detector → `update_user_fact`

## Graph-ingest gate (spec §7)

The gate has three layers:

- **Fast-reject:** short inbound (<20 chars), ambient filler ("lol", "k"),
  `stay_silent` with no tool work.
- **Fast-accept:** multi-message burst (≥2 outbound), OR any recall tool used
  this turn.
- **Haiku judgment:** claude-haiku-4-5 called on the fuzzy middle.

Verdicts are logged to `DONNA_GATE_LOG` (JSONL) for later tuning. Target
ingestion ratio is 40–60% of turns.

## Tuning the gate

1. Collect ≥100 verdicts from `DONNA_GATE_LOG`.
2. Compute `fast_accept / total`, `fast_reject / total`, `haiku / total`.
3. If ingestion is **>60%**: extend the fast-reject ruleset (more filler
   patterns, tighter length threshold).
4. If ingestion is **<40%**: extend the fast-accept ruleset (e.g., single-
   sentence inbound with emotional markers).
5. If the Haiku layer dominates (>40% of decisions), invest in prompt
   tightening — cheap wins live there.

## Per-user isolation (spec §12)

- Supermemory: always pass `container_tag=user_id` on `add`/`search`.
- Graphiti: `group_id = user_id.replace("-", "")`, and
  `_route_to_user_db(g, group_id)` before every search.
- Postgres: every table is keyed on `user_id` with index `(user_id, …)`.

## Runtime wiring

- [donna_runtime/tool_logic.py](../donna_runtime/tool_logic.py) calls
  `backend.memory.tools.*` instead of the old `FAKE_MEMORY`/`FAKE_TRACKERS`.
- [donna_runtime/hooks.py](../donna_runtime/hooks.py) fans out the four
  memory hooks on `send_burst`.
- [donna_runtime/prompt.py](../donna_runtime/prompt.py) renders the Living
  Profile from `users.living_profile` when available; falls back to the seed.
