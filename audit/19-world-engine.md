# 19 — world engine

## what this is supposed to be

Donna's senses for the outside world. Two modes:
1. **Reactive** — the world pokes her (email arrives, calendar event created), she scores it and decides whether to surface it.
2. **Active** — she goes out and looks at the world for the user (news on tracked companies, sector moves, friend launches, watched stocks). The user said "watch X" and she watches.

A real thinking partner needs both. A WhatsApp bot that only listens to webhooks is a notifier. A donna who watches the world for you is the actual product.

## what's actually there

### reactive world (works)

**Email path** — `backend/integrations/proactive_email_trigger.py`
- Composio Gmail webhook lands → `score_email` (`email_importance.py`) computes a 0-1 importance with a `ScoringContext` of the user's open loops + biography → above `THRESHOLD = 0.5` it goes to the dispatcher.
- `proactive/dispatcher.py` is the unified funnel. Order:
  1. `can_fire_proactive` — quota / cooldown / quiet hours arbiter (`backend.integrations.proactive_rate_limit`).
  2. `judge_event` — Tier 2 Haiku judge produces ship/hold/drop with a draft.
  3. `voice_validator.validate` — uppercase / emoji / em-dash check, with one re-author retry (line 687–793).
  4. `_ship_draft` (sends WhatsApp + writes ChatMessage + ProactivePing) OR `insert_pending_note` (hold lane, 12h TTL) OR `_escalate_to_brain` (donna_turn proactive mode, when needs_tools or voice fails).
- Mirror mode default; tiered mode with `DONNA_PROACTIVE_TIERED=1`.
- Other Composio integrations: `bootstrap_calendar.py`, `bootstrap_gmail.py`, `calendar_ingest.py`, `gmail_ingest.py`, `oauth_watcher.py`, `label_router.py`. Webhook handling, normalization, ingestion. All present, all wired.

**Calendar path** — `proactive/spawners/calendar.py`
- New event lands via `calendar_ingest.ingest_calendar_event` → `maybe_spawn` classifies (regex/keyword first, Haiku fallback for ambiguous) → emits attentions for stakes_meeting, prep_doc, etc. → those attentions become reminders/watches/briefs in the attention subsystem.
- Daily 24h-ahead sweep via `spawner_worker`.
- Routine recurring events deliberately left to `CalendarRecurrenceProposer`.

**Attention sources** — `proactive/sources/`
- `attention_fire.py`, `attention_offer.py` adapt fired/offered attentions into `ProactiveEvent` for the unified dispatcher.
- `email.py` adapts incoming email rows into the same `ProactiveEvent` shape.

This whole reactive layer is real and has tests. The arbiter, judge, voice validator, dispatcher are the cleanest piece of the proactive stack.

### active world (mostly built, mostly orphaned)

**The Exa pipeline** — `backend/web/`
- `client.py` — httpx client with full Exa surface: search, find_similar, contents, **research_create, webset_create, monitor_create**. The advanced lanes (research / webset / monitor) are wrapped.
- `expansion.py` → `fanout.py` → `rerank.py` (RRF + optional Cohere) → `synthesis.py` (two-prompt strict-vs-broad + judge).
- `pipeline.py:run_web_research` is the orchestrator. Mirrors the memory retrieval pipeline shape.
- `evals/` — questions + rubric + run_eval.

**Brain access (in-conversation)** — `donna_runtime/tools.py`
- `web_search` (line 1389) — single-shot Exa search via `exa_search`. Wired.
- `agentic_web_search` (line 1457) — multi-source Exa research. Wired.
- `research` (line 1553) — calls `backend.web.pipeline.run_web_research`. Wired.
- `recall_document_chunks` — Supermemory document chunks, separate from Exa.

These three are real, called from the brain at turn time, and have when-to/when-not clauses. **In-conversation web access works.**

**Proactive Exa runner** — `backend/web/proactive/runner.py`
- `run_proactive_tick(user_id)` is the orchestrator: build_context → query_creation → gates → executor → judge → mark.
- `query_creation.py` Haiku-decides 0–3 ProactiveMoves anchored on Living Profile + Situation Brief + recent thread. Specifically forbids generic news, wellness, "you might like."
- `executor.py` dispatches to the right Exa lane (search / find_similar / research / webset / monitor).
- `judge.py` decides per-result whether the finding earns a ping, with default-to-silence.
- `gates.py` does cost budget + dedup ledger.

**`run_proactive_tick` is dead code in production.** Only callers:
- `scripts/proactive_dry_run.py` (CLI dev script)
- `backend/tests/test_proactive_*` (tests)

No worker invokes it. No webhook invokes it. The Exa proactive engine — the thing that would make Donna actively watch the world — is fully built, fully tested, and never runs in prod. The only proactive thing the synthesis worker calls is `maybe_fire_morning_check_in` (which lifts existing LP signal — it does NOT do fresh web fetches).

### watchlists (do not exist)

There is no `user_watchlists` table. No `watched_entities`. The closest things:
- `attention.subject` — when a user accepts a structure ("watch ADBE"), the attention's subject carries the entity name. But this is a Donna-internal construct, not a "watch the world for changes on X" subscription.
- Exa `webset` and `monitor` lanes — exist in the executor (line 143–162), but no DB row anywhere persists "this user has a webset for design-tool launches." If `run_proactive_tick` doesn't run, websets and monitors don't get created.
- The `watch` tool referenced in CLAUDE.md as a tool category — search of `donna_runtime/tools.py` shows no actual tool named `watch`. It's an attention card-type, surfaced through the existing schedule/attention machinery, not a web-facing watchlist primitive.

### news brief / brief archetype

- Dashboard has `NewsBriefBlock.tsx` — frontend component for 1–3 curated cards.
- `backend/dashboard/compose.py` line 152 lists `news-brief` as an allowed block kind.
- But `compose_manifest` reads `living_profile` + situation + observations and asks Haiku to compose a plan. There's no fetch step that brings in fresh web items before composing. So the `news-brief` block, if emitted, gets its content from whatever's already in the LP — which is yesterday's chat / observations, not today's web. **The block is template-only.**

## what works vs what's broken

**Works:**
- The reactive layer end to end: webhook → score → dispatcher → judge → voice net → ship/hold/drop. Mirror mode is the conservative default. Tier 2 ships drafts directly when the flag is on.
- In-conversation web tools (`web_search`, `agentic_web_search`, `research`) are real and called from the brain.
- The web research pipeline (expansion → fanout → RRF → synthesis) has evals and degrades gracefully.
- Exa client wraps the full advanced surface (research/webset/monitor) — the building blocks are there.

**Broken / missing:**
- `run_proactive_tick` has no production caller. The active-world half of the world engine doesn't run. Adding one cron entry on the synthesis worker (or a new worker role) would change everything.
- No `user_watchlists` table. The notion of "things this user wants Donna to watch" is implicit (LP narrative + active attentions), not first-class. Exa websets are built but never persisted per-user.
- The news-brief dashboard block has no backend fetch. The frontend renders content the composer never produced fresh.
- No "I have set up a webset for you" flow. No way for the user to say "watch Anthropic releases" and have Donna actually create an Exa monitor that webhooks back when something hits.
- Tier 2 voice re-author imports private symbols (`from proactive.judge import _build_user_message, _gather_inputs, _load_prompt, _validate_output, _call_haiku`) — fragile, but works.

## opinion — reactive vs active world

A donna who only knows about the world via webhooks is a smart inbox, not a thinking partner. Webhooks are the world pushing at her. The user has to be the source of every world signal — by sending an email, by accepting a meeting, by typing into WhatsApp. That's reactive. That's tier 1.

A donna who watches the world for her user is the product promise in CLAUDE.md: "thinking partner with persistent memory, high-agency." High-agency means going out and getting the relevant signal *before* the user asks. Anchor on what the user told you they care about (the LP narrative says "user is choosing between Poke and Limitless for pitch days"). Run an Exa search at a sensible cadence. Judge whether anything new lands. If yes, ping. If no, stay silent.

This is `run_proactive_tick`. It exists. It has the right shape — query_creation forbids generic news, ties to user signal, judge defaults to silence. The cost discipline is built in (CostBudget, DedupStore). It's a one-day wiring job to set up a worker that calls it on a schedule.

**How far is the codebase from each?**
- From reactive world: shipped. Tier 2 mirror mode is running; the flip to tiered is one env var.
- From active world: maybe two days of work. Wire `run_proactive_tick` into a worker that runs every N hours per active user, with a dedup ledger that survives restarts (the in-memory one doesn't). Add a `user_watchlists` table or use `living_profile.watch_for_tomorrow` as the seed. Hook the news-brief dashboard block to `ProactiveResult` payloads marked `render_hint=card`. Done.

The piece that's really missing is the **persistence of watch intent**. Right now if the user says "watch Adobe earnings," Donna would handle it as a one-off recall or a reminder. There's no first-class concept of "this user has subscribed Donna to ongoing coverage of X." You can fake it with attentions, but the attention machinery is reminder-shaped, not subscription-shaped. The Exa webset/monitor lanes are perfect for this and unused.

## verdict

- **Architecture: 8/10** — Reactive layer is well-shaped (dispatcher pattern, voice net, hold lane). Active layer's pipeline is well-shaped too (deterministic glue, decisions in modules). Both follow the project's "every capability is a tool, every side-effect is a hook" rule.
- **Production: 5/10** — Reactive runs (mirror mode minimum). Active is dead code. The half that's the actual product differentiator is shelved.
- **Gap to vision: medium-large** — Today's donna is mostly reactive. The active-world half exists but doesn't run. Vision says high-agency thinking partner who watches the world; reality says smart email triage with proactive web available only when the user asks in-chat. The code is closer to the vision than it looks because most of the active-world plumbing is already written. Wire it up and persist watch intent and this jumps to 8/10 production.
