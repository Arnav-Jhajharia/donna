# ctx-industry Challenge Response (sharp, specific)

## Cache breakpoints — ordering
1. `_DONNA_CORE` (1,400 tok) — bp1, **1h TTL**.
2. `tool_catalog` (all schemas) — bp2, 1h TTL.
3. `user_facts_stable` (Living Profile JSONB) — bp3, 5m TTL.
4. Per-turn volatile (local_time, recent chat, open loops, tracker) — **NO breakpoint, tail only**.

Current bug: `render_turn_context` placed upstream of user message kills cache. Fix: push after bp3. Strip `local_time` from prefix entirely — expose via `get_local_time()` tool or inject after last breakpoint.

## Tools to cut/merge (target ≤12)
- **Merge** `read_situation_brief` + `refresh_situation_brief` → `situation_brief(refresh=False)`.
- **Merge** `track_open_loop` + `close_open_loop` + `log_observation` → `record(kind: "loop_open"|"loop_close"|"observation", ...)`.
- **Merge** retrieval family (`recall_*`, `read_*`, `list_*`) → `recall(source: "graph"|"episodic"|"docs"|"facts", query, filters)`. Six → one.
- **Cut** any dashboard tool absent from last 500 traces.
- **Merge** `add_insight_card` + `flag_attention` if overlapping.
- Keep unmerged: 4 terminators (send_burst, stay_silent, offer, draft_high_stakes_message) — control-flow exits.

## Subagent context sharing
Cognition answer: **share parent trace, don't re-read.** `draft_high_stakes_message` receives compressed parent trace (system + cached user_facts + last N tool calls with results) as a single blob, runs on Sonnet/Opus, returns one draft string. Read-only, no writes, no tools. Pure function over parent state.

## Graphiti vs Postgres
For single-user Donna, **Postgres-only wins.** Schema:
```
facts(subject, predicate, object, t_valid_start, t_valid_end, t_created, t_expired, embedding)
```
Reproduces ~90% of Graphiti value. Lose: multi-hop traversal (rare for one user), entity coreference at scale (add LLM-extraction dedup + canonical-name unique index), community clusters (Park-style reflections work over flat table).

**Verdict**: ship Postgres-only for v2. Revisit Graphiti only if multi-tenant.

## Proactive triggers — concrete rules
Cron at 5-min resolution evaluating:
1. **Calendar edge**: event importance ≥7 starts in [10, 25] min AND Donna silent on it last 2h → fire.
2. **Open-loop staleness**: due−now < 24h AND last_nudge > 48h ago → fire.
3. **Silence-after-burst**: user sent ≥3 messages in 15min, then ≥90min silence, last Donna msg was a question → gentle check-in.

Invoke same BRAIN loop with `mode="proactive"`.

## Errors + max_turns
"3 is the real bug." Raise to **6–8 reactive, 12 proactive**. At max_turns=3 after one error, 1.5 productive turns remain — errors' tokens compete with useful context. At 6-8 with caching, still <$0.01. Compress errors immediately only if retry depth insufficient.

## `recall_similar_situation` spec
- Query: embed `(last_user_message || open_loops_summary)`. NOT full turn.
- k = 3.
- Filters: `t_valid > now − 180d`, `importance ≥ 5`, exclude last-24h episodes.
- Anti-rut (Manus few-shot trap):
  1. Sample k=3 from top-10 with weighted randomness, not top-3 deterministic.
  2. Re-serialize each with different template per turn (bullet, narrative, Q/A).
  3. Never >1 episode with same entity cluster.
- Ranker: Park's `recency + importance + relevance` + diversity filter.
