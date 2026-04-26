# Memory + Situational Awareness Wire-Up Plan

Goal: close the three real gaps in Donna's memory layer so the temporal brief
is genuinely live in production, and the bitemporal facts substrate actually
gets used. Everything that follows is wiring, not new architecture.

## Context (what's already true)

- `backend/memory/synthesis/temporal_brief.py` is shipped and tested. Plan 2
  (`windowed_timeline`) scored 86–90 in stress tests and is the production
  default.
- The brief is persisted to `users.living_profile["situation_brief"]` and
  rendered into the cached system prompt via
  `backend/memory/user_facts/rendering.py:60-88` →
  `donna_runtime/prompt.py:_inject_user_model`. This path works.
- `backend/memory/facts/bitemporal.py` (commit 7cc635b) is a proper
  bi-temporal repository (`record_fact`, `update_fact`, `supersede_fact`,
  `get_current`, `get_as_of`, `list_history`). Zero production callers today.
- `donna_runtime/observability.py` emits structured events to
  `.donna/events.jsonl`, already consumed by
  `dashboard/web/app/api/events/route.ts` with p50/p95 percentiles.

## Three gaps this plan closes

1. **No periodic brief refresh.** Post-write best-effort only. Chat-only
   users go stale for days. `scripts/refresh_situation_briefs.py` has no
   cron/startup wiring.
2. **`read_situation_brief` is not a model-callable tool.** Registered in
   `backend/memory/tools/__init__.py:ALL_TOOLS` but absent from
   `donna_runtime/config.py:ALLOWED_TOOLS` and `donna_runtime/tools.py:DONNA_TOOLS`.
3. **Bitemporal facts table is empty plumbing.** The shape is right for
   timezone authority ("user's tz was SG from X; as of Y it's NYC") but
   nothing writes facts into it.

---

## Phase 1 — Expose `read_situation_brief` as a model-callable tool

**Files:**
- `donna_runtime/config.py`
- `donna_runtime/tools.py`

**Steps:**

1. `donna_runtime/config.py:ALLOWED_TOOLS` — add
   `"mcp__donna__read_situation_brief"` before the `send_burst` entry.
   (Already done in the prior session — verify it's still there.)
2. `donna_runtime/tools.py` — add a `@tool` wrapper after
   `resolve_time_expression` (around line 425). Follow the `list_calendar`
   pattern: no args, use `_current_user_id()`, return via `_tool_text(...)`.
   Description: "Read the raw stored situation brief (last/this/next week
   model), including generated_at timestamp and evidence counts. Use to
   verify freshness or cite evidence counts. Do NOT use for normal
   'what's my week' questions — the rendered brief is already in the system
   prompt."
3. Register the symbol in the `DONNA_TOOLS` tuple at lines 614–628, before
   `send_burst`.
4. Run `pytest tests/test_donna_runtime.py -q` to confirm no regressions.
5. Commit: `feat(tools): expose read_situation_brief to model`

---

## Phase 2 — Periodic brief refresh background task

**Files:**
- `backend/memory/jobs/temporal_refresh.py` (add `run_forever`)
- `api/main.py` (startup + shutdown hooks)

**Steps:**

1. Add `run_forever(poll_interval_s: float = 7200.0, active_within_days: int = 14, ...)`
   at the bottom of `backend/memory/jobs/temporal_refresh.py`. Pattern:
   mirror `backend/memory/jobs/schedule_worker.py:130-143`. Body: infinite
   loop calling `refresh_active_user_briefs(...)`, try/except around each
   tick, `asyncio.sleep(poll_interval_s)` between. Log one-line summary
   per tick (refreshed/failed/selected counts).
2. `api/main.py:53` — add module global `_brief_refresh_task: asyncio.Task | None = None`.
3. `api/main.py:287-295` startup hook — after the `DONNA_SCHEDULE_WORKER`
   block, add parallel `DONNA_BRIEF_REFRESH` gate that spawns
   `temporal_refresh.run_forever(...)` as `_brief_refresh_task`. Read
   optional `DONNA_BRIEF_REFRESH_INTERVAL_S` env var (default 7200).
4. `api/main.py:298-307` shutdown hook — cancel `_brief_refresh_task` with
   the same pattern as `_schedule_task`.
5. Test locally: `DONNA_BRIEF_REFRESH=1 DONNA_BRIEF_REFRESH_INTERVAL_S=60`
   → boot the app → verify a tick runs in logs and briefs get updated for
   active users.
6. Commit: `feat(memory): periodic brief refresh background task`

**Cadence decision:** default 2h (7200s). Operator can override via env.
A future enhancement can add active/idle tier split; not doing that now.

---

## Phase 3 — Wire bitemporal facts for timezone

**Files:**
- `backend/memory/tools/set_timezone.py`
- `backend/memory/facts/bitemporal.py` (decorator only)
- `backend/memory/user_facts/api.py` or wherever `current_timezone` /
  `home_timezone` get extracted (confirm by grep before editing)

**Design:**

- `users.timezone` column stays as the operational cache and read path.
  Everything that currently reads it keeps working.
- Bitemporal `Fact` rows become the history / authority layer. On every
  timezone write, also insert/update a `Fact(subject="user",
  predicate="timezone", object=<IANA tz>)`.
- Decision matrix inside `set_timezone`:
  - If `get_current(user_id, "user", "timezone")` returns None →
    `record_fact(...)`.
  - If the existing current belief's object equals the new tz → no-op on
    the bitemporal side.
  - Else → `update_fact(old_id=<current.id>, new_object=<tz>, t_valid_from=now)`.
    (State change, not correction. `supersede_fact` is only for "we were
    wrong.")

**Steps:**

1. Confirm the extractor path: grep for `current_timezone` in
   `backend/memory/user_facts/` and wire the same record/update logic
   there (source="conversation_extracted" or similar).
2. Edit `set_timezone.py` — after the existing `users.timezone` /
   `onboarding_goals` / `facts` writes commit, open a new session (or the
   same session before commit) and do the bitemporal insert/update. Wrap
   in try/except so a bitemporal failure doesn't block the primary write.
3. Add the same hook to the fact extractor path for `home_timezone` /
   `current_timezone`.
4. Tests: add `backend/tests/test_timezone_bitemporal.py` covering:
   (a) first set → `record_fact` row exists;
   (b) same tz again → no new row, no `update_fact`;
   (c) different tz → `update_fact` closes old, inserts new, history has 2 rows;
   (d) `get_as_of(at_valid=past)` returns the old belief.
5. Commit: `feat(memory): route timezone writes through bitemporal facts`

**Not in scope this phase:** migrating `resolve_time_expression` to read
from bitemporal (it reads `users.timezone` directly — leave alone). Making
bitemporal the read path is a follow-up once history is populated.

---

## Phase 4 — Observability on the new paths

**Files:**
- `backend/memory/facts/bitemporal.py`
- `backend/memory/jobs/temporal_refresh.py`
- `donna_runtime/tools.py` (only if the new wrapper needs it — backend
  tool is already decorated)

**Steps:**

1. Decorate `record_fact`, `update_fact`, `supersede_fact`, `get_current`,
   `get_as_of` with `@instrument_memory_op("postgres.facts")`. Signatures
   accept `session` as first positional and `user_id` in kwargs, confirm
   `instrument_memory_op` handles that — if not, call `emit(...)` manually.
2. In `run_forever`, emit a periodic event per tick:
   `emit("memory.brief_refresh.tick", payload={"refreshed": n, "failed": m, "selected": k})`.
3. Verify events appear in `.donna/events.jsonl` after a local run and
   render in the dashboard.
4. Commit: `feat(observability): instrument bitemporal facts and brief refresh`

---

## Phase 5 — Eval fixtures

**Files:**
- `donna_runtime/smoke_eval_fixtures.py` (extend)
- Optionally `donna_runtime/smoke_eval_multiturn.py` for cross-turn arcs

**Fixtures to add:**

1. **Brief freshness probe.** Single-turn. User: "how fresh is what you
   know about my week?". Expected tool call: `read_situation_brief`.
   Expected reply: references `generated_at` timestamp.
2. **Timezone correction propagates.** Multi-turn arc (goes in
   `smoke_eval_multiturn.py`):
   - Turn 1: "set my timezone to America/New_York"
   - Turn 2: "what timezone do you have for me"
   - Turn 3 (after simulated time jump): confirm `get_current` returns NYC,
     `list_history` has 2 rows.
3. **Brief refresh under chat-only load.** If feasible, a fixture that
   advances mock time past the refresh interval and confirms the brief
   regenerates without any write tool being called.

**Steps:**

1. Add fixtures following existing shapes in `smoke_eval_fixtures.py`.
2. Run `pytest tests/test_smoke_eval.py -q` for structural checks.
3. Run `DONNA_LIVE_EVAL=1 pytest tests/test_live_smoke_eval.py -v -s` for
   the live-model check (requires API key).
4. Commit: `feat(eval): fixtures for brief freshness and tz history`

---

## Test cadence

After each phase: `pytest backend/tests tests -q`. Full eval runs (live)
only after phases 1–3 land together — Phase 4 and 5 don't change
user-observable behavior.

## Out of scope (explicitly deferred)

- Making `users.timezone` a derived cache of bitemporal `get_current` —
  possible follow-up once history has real rows.
- Calendar sync path (Google → Postgres). Not touched.
- Procedural rules Tier 1/3 — dead, separate decision.
- Attention subsystem brain integration — blocked on DB table design,
  separate multi-week project.
- CLAUDE.md nine-backend framing cleanup — documentation follow-up.

## Order / dependencies

Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5. Each phase ships a
commit. Don't batch. Phase 3 has no runtime dependency on phase 2, but
logical order keeps each PR small.
