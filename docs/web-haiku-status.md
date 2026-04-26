# `backend/web/` + Haiku — status checkpoint

Captured 2026-04-26 before pivoting away from the dashboard work, so we
can pick this up later without re-deriving where it stands.

## What this subsystem is

Two distinct things live under `backend/web/`:

1. **The web research pipeline** (`pipeline.py`, `expansion.py`, `fanout.py`,
   `rerank.py`, `synthesis.py`, `client.py`, `search.py`). Powers Donna's
   `web_search`, `agentic_web_search`, and `research` brain tools.
2. **The proactive subsystem** (`backend/web/proactive/`). The "decide what
   to look up before the user asks" loop. Built and tested. **Not wired
   into any production trigger** — only fires via `scripts/proactive_dry_run.py`.

## Where Haiku is used

All Haiku calls go through `backend.memory.retrieval.structured.call_structured`
(tool-use mode, Pydantic-validated, timeout-bounded). Model id:
`claude-haiku-4-5-20251001`.

| File | What Haiku does | Wired to brain? |
|------|-----------------|-----------------|
| `expansion.py` | Rewrites the research question into 1-3 neural queries + 1-2 keyword queries + optional HyDE snippet | ✅ via `research` tool |
| `synthesis.py` | Two-prompt strict-vs-broad synthesis + judge picks `strict` / `broad` / `merged` | ✅ via `research` tool |
| `pipeline.py` | Orchestrates expand → fanout → dedup → RRF → optional Cohere rerank → synthesize | ✅ via `research` tool |
| `proactive/query_creation.py` | Reads ProactiveContext (Living Profile + Situation Brief + recent thread + time), emits 0-3 ProactiveMoves across Exa surfaces (search / find_similar / research / webset / monitor) | ❌ unwired |
| `proactive/judge.py` | Worth-telling judge: given the result, is it worth pinging the user? Returns `send` (with draft message in Donna's voice) or `silence` | ❌ unwired |
| `evals/rubric.py` | Rubric judge for baseline-vs-pipeline answer comparison (specificity / citation_quality / coverage / calibration) | offline eval only |

## Brain wiring (research path)

`donna_runtime/tools.py` exposes three brain tools backed by `backend/web/`:

- **`web_search`** — single-fact lookup. Calls `backend.web.search.search_web`. Cheapest.
- **`agentic_web_search`** — multi-source lookup. Provider reads several pages on its own.
- **`research`** — full pipeline (`backend.web.pipeline.run_web_pipeline`). The strict-vs-broad synthesis lives here.

All three are in `donna_runtime/config.ALLOWED_TOOLS`.

## Proactive subsystem — built but never fires

`backend/web/proactive/` is a complete, layered, tested implementation:

```
build_context → create_moves → apply_gates → execute → judge → mark
       │              │              │           │         │       │
       │              │              │           │         │       └ ledger marks intents
       │              │              │           │         │         so the same move doesn't
       │              │              │           │         │         fire again before TTL
       │              │              │           │         │
       │              │              │           │         └ Haiku decides send/silence
       │              │              │           │
       │              │              │           └ executes via Exa client
       │              │              │
       │              │              └ rate-limit + budget + dedup gates
       │              │
       │              └ Haiku invents 0-3 moves
       │
       └ assembles Living Profile + Situation Brief + recent thread + time
```

What's missing is the **trigger**. Nothing schedules `run_proactive_tick`.
Options when we come back to this:

1. APScheduler / cron job in the Railway worker process.
2. A PostToolUse hook that fires after specific brain tools (e.g. after a
   `recall` returns nothing, ask: should we proactively search?).
3. An ingress hook on idle (no message from user in N minutes, run a tick).

The runner is intentionally side-effect-free for delivery — it returns the
verdicts and drafts, and the caller decides whether to push them onto the
WhatsApp queue, surface them as dashboard nudges, or log as shadows.

Tests at `backend/tests/test_proactive_*.py` cover all five stages.

## Tests on the research side

- `backend/tests/test_web_pipeline.py` — pipeline end-to-end with stubbed Haiku + Exa.
- `backend/tests/test_web_search.py` — single-search behavior.
- `backend/tests/test_web_eval.py` — rubric judge sanity.

## How to pick this up later

1. **If shipping the research path further:** the brain tools already work;
   the lever is the system prompt's when-to-use guidance for `research`
   vs `agentic_web_search` vs `web_search`. Sonnet sometimes reaches for
   the wrong one — tighten the descriptions.

2. **If wiring the proactive subsystem live:**
   - Pick a trigger (cron is simplest for v1).
   - Decide delivery: silent shadow log, dashboard nudge, or WhatsApp draft.
   - Surface a kill-switch env var (`DONNA_PROACTIVE_ENABLED=0`) so we can
     turn it off without a deploy if it misbehaves.
   - The cost ceiling is real: 5 ticks/day × 0-3 moves × Haiku cost is
     trivial, but the executor's Exa calls add up. Budget is enforced in
     `gates.CostBudget` — verify the cap before turning it on.

3. **If pulling Haiku out:** the only places that matter are
   `expansion.py`, `synthesis.py`, `proactive/query_creation.py`,
   `proactive/judge.py`, and `evals/rubric.py`. All five would need a
   substitute (Sonnet would work but at ~10× cost; a smaller open model
   would need eval validation against the existing rubric).

## Environment

Required for the research path to actually call out:

- `ANTHROPIC_API_KEY` — Haiku.
- `EXA_API_KEY` — search/find_similar/research backends.
- `COHERE_API_KEY` — optional, for the rerank node (pipeline degrades
  gracefully without it).

## Recent commits that touched this

```
220ee5e feat(integrations): Phase 1 — Composio auth round-trip
412610a feat(scripts): haiku judge for memory stress runs
276d95c feat(scripts): memory stress-test harness
36fb102 feat(scripts): deterministic seed corpus for memory stress test
```

The stress harness is separate from `backend/web/` but also uses Haiku
(as a verdict judge for memory recall quality). See
`scripts/_stress_matrix/haiku_judge.py`.
