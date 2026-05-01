# Audit 08 — Search and Research

What this covers: how Donna goes outside her own memory to learn things — both the quick "look something up" path and the heavier "do real research" path.

## What's there

Three brain-facing tools, all defined in `donna_runtime/tools.py`:

1. **`web_search`** (`donna_runtime/tools.py:1347-1418`) — single-shot lookup, returns 3-5 hits. Backed by Exa's `/search` endpoint (`backend/web/search.py:108-143`, `backend/web/client.py:88-134`). Supports a `recency` filter (day/week/month/year). Returns formatted `- title (url) — snippet` lines.

2. **`agentic_web_search`** (`donna_runtime/tools.py:1421-1480`) — provider-side synthesis. Backed by **Tavily** with `search_depth=advanced` and `include_answer=True` (`backend/web/search.py:146-180`). Returns one synthesized answer plus up to 5 sources. Kept as the eval baseline.

3. **`research`** (`donna_runtime/tools.py:1507-1590`) — deep multi-stage pipeline. Calls `backend/web/pipeline.py:run_web_research`. This is the real thing.

The research pipeline (`backend/web/pipeline.py`) is genuinely well-shaped. Five stages:

- **expand** (`backend/web/expansion.py`) — Haiku rewrites the question into a terse query plus 1-3 neural-style queries plus 1-2 keyword queries plus an optional HyDE one-liner. Falls back to a naive single query if Haiku is missing.
- **fanout** (`backend/web/fanout.py`) — every expanded query becomes one async Exa call. `find_similar` lane added when `seed_url` is given. `asyncio.gather(return_exceptions=True)` so one lane failing never sinks the pool.
- **dedup + RRF** (`backend/web/rerank.py:41-93`) — collapse duplicate URLs, then Reciprocal Rank Fusion across retrieval lanes. Robust to score-scale differences between neural and keyword.
- **Cohere rerank** (`backend/web/rerank.py:96-152`) — optional cross-encoder pass with rerank-v3.5. Degrades cleanly when `COHERE_API_KEY` is unset.
- **two-prompt synthesis + judge** (`backend/web/synthesis.py`) — strict and broad prompts run in parallel over the same source pool, then a third Haiku judges and picks `strict | broad | merged` plus confidence and dissent. Three Haiku calls max per `research` invocation.

Eval suite is real (`backend/web/evals/run_eval.py`). Five hand-picked questions in `backend/web/evals/questions.py` (Poke vs Limitless, Claude SDK vs LangGraph, Exa vs Tavily, OpenAI roadmap, Linear vs Height). Each one runs Tavily as baseline, the Exa pipeline as challenger, then a rubric judge in `backend/web/evals/rubric.py` scores both on specificity, citation quality, coverage, calibration. Skips cleanly when keys are absent.

Document recall (`backend/memory/tools/recall_document_chunks.py`) is separate — searches Supermemory chunks of files the user previously sent, by name/topic/quote. Optional `doc_id` scopes to one doc.

## What works

- Three tools cover three real cost tiers. `web_search` is cheap, `agentic_web_search` outsources synthesis to Tavily, `research` is the bespoke deep pipeline. Tool descriptions actually carry when-NOT-to-use clauses (the CLAUDE.md gospel).
- The pipeline architecture is correct on paper and on disk. Expand → fanout → RRF → rerank → two-prompt synthesis with a judge is what a serious researcher would build. RRF in particular is the right call when you mix neural + keyword lanes with incomparable scores.
- Degradation is taken seriously at every node — missing key, lane failure, Haiku timeout — pipeline never raises. Returns empty `WebAnswer` with a `reason` instead.
- Tests exist (`backend/tests/test_web_pipeline.py`, `test_web_search.py`, `test_synthesis.py`, `test_exa_client.py`, `test_web_eval.py`).

## What's broken or missing

- **The promised subagents do not exist.** CLAUDE.md says `dig_deeper` and `compile_brief` are tools. They aren't. `grep -rn "dig_deeper\|compile_brief" --include="*.py"` finds zero hits in code, only `docs/how-donna-works.md:288-509` flagging them as **MISSING**. Donna has `research` but no Opus-backed subagent that hides latency, returns a compressed artifact, and lives at the edge of the BRAIN loop the way the gospel describes.
- **No research caching.** Every `research` call re-runs the full pipeline. A user asking "what's new in AI agents this week" twice in two hours pays twice. Exa hits, Cohere hits, three Haiku synth calls — no SHA-of-question dedupe, no TTL, nothing in `pipeline.py` or `client.py`. The pattern of users asking the same question across the day is real.
- **Cost discipline is asserted, not bounded.** Every stage *uses* Haiku to keep cost down (good), but per-turn there's no token budget, no "if the question is small don't run two-prompt synth," no early exit. A `research` call burns ~3 Haiku calls + ~5-10 Exa fanouts + a Cohere rerank + downloaded contents every time.
- **Tavily is in two places at once.** `agentic_web_search` is "still backed by Tavily, kept as the eval baseline" (`search.py:1-13`). That's a smell — it's both shipped to users *and* the comparison target. Either it's a real tool or it's eval scaffolding. It cannot be both without confusing the brain about when to call it.
- **No LangSmith / observability hooks on the pipeline itself.** `web_search` and `research` are `@traceable`, but the inner expansion / fanout / rerank / synthesis nodes are not. Hard to debug "why did the answer go sideways on q2."
- **Eval suite exists but has no CI integration visible.** `run_eval.py` is hand-run from the CLI. No nightly cron, no PR gate, no historical scoreboard. CLAUDE.md says "Never merge without running evals" — the runway exists, the muscle does not.

## Opinion vs Donna's vision

A Donna who can do **real** research is a different product from a Donna who can web-search. The vision is "thinking partner with persistent memory" — a partner is the person who comes back with "here's the actual answer, here's what's contested, here's where I'd push back," not the person who hands you a list of links.

The pipeline architecture says "real research." The reality is closer than I expected. Two-prompt synth with a judge is the part most teams skip — Donna has it, and it's the right design. RRF + optional Cohere is also serious. So when a user asks "summarize the state of the AI agent space this week," the pipeline *can* return a thoughtful brief with confidence and dissent, in Donna's lowercase voice.

But the gap between "can" and "does reliably" is the eval discipline. The eval ships, but it has to be run by a human. No CI gate, no rolling scoreboard, no regression alarm. So you don't actually know whether yesterday's edit to the rerank threshold quietly broke q3. That's where this falls short of the high-agency posture — high-agency requires legibility, and the eval pipeline is currently a kind of trust-me-bro.

The missing subagents (`dig_deeper`, `compile_brief`) are the bigger ideological gap. The gospel says: keep the BRAIN loop tight, push expensive work into Opus subagents that return compressed artifacts. Right now `research` runs *inside* the BRAIN loop and spends 3+ seconds at the user's expense. That's not awful — degradation is graceful — but it's the wrong shape. A `dig_deeper` subagent, fired as fire-and-forget with a follow-up burst, is what the doc promises and what would actually feel different in WhatsApp.

## Verdict

The research pipeline is the most architecturally serious thing in this audit. It's well-shaped, well-degraded, well-tested in code, and defensibly designed end-to-end. But it's underwired into the agency layer (no subagent), unbounded on cost (no cache, no budget), and underwatched on quality (no automated eval gate). Donna can already give a thoughtful brief on "state of AI agents this week" — she just can't tell you if she's been getting worse at it. Ship as-is for v1, but the next two weeks should add: (1) a content-keyed result cache with a 6-12h TTL, (2) the `dig_deeper` subagent so this stops blocking the BRAIN loop, (3) eval CI with a regression alert. Tavily-as-baseline-and-shipped-tool also needs a decision — pick one.
