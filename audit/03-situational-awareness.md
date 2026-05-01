# 03 · Situational Awareness

In this codebase, "situational awareness" means the **Living Profile** — a JSONB blob on the `users` table that gets re-synthesized periodically and rendered into Donna's system prompt every turn.

## What's captured (Living Profile schema)

Stored at `users.living_profile`. About 15 structured fields:

| Field | What it is | Read by |
|---|---|---|
| `narrative` | A one-paragraph (≤800 char) story of who the user is right now | brain prompt, dashboard composer, morning trigger |
| `running_themes` | Up to 3 short phrases (60c each) — the things on her mind | brain prompt |
| `key_people` | Up to 4 people, each with name + role + current dynamic | brain prompt |
| `rhythm.typical_first_engage_window` | When the user usually opens their phone in the morning | brain prompt, morning trigger gate |
| `rhythm.typical_wake_window` | Sleep boundary | brain prompt |
| `rhythm.typical_quiet_hours` | When NOT to ping | **never read** ← orphan |
| `rhythm.typical_message_gap_median_hours` | Spacing between messages | rendered for show, never used in decisions |
| `emotional_temperature` | One word — calm/focused/stressed/anxious/conflicted/proud | brain prompt, dashboard composer |
| `active_tensions` | Up to 3 short tensions (e.g. "deadline + dad's call") | brain prompt |
| `today_shape` | A short paragraph describing today | brain prompt, morning trigger |
| `watch_for_tomorrow` | Up to 4 things Donna should be ready for | brain prompt + **morning trigger gate** |
| `yesterday` | A digest of yesterday's misses + anomalies | brain prompt |
| `what_changed_this_week` | Synthesized but **never rendered** ← orphan |
| `current_situation` | v1 legacy fallback — only used if narrative is empty | semi-orphan |
| `signal` | Counts dict (chat msgs, observations, etc.) | observability only |
| `morning_proactive_last_fired_at` | "Did I already do morning today?" idempotency stamp | morning trigger |

There's a separate write path that produces the v1 `situation_brief` (last week / this week / next week temporal slices) via `temporal_brief.py`. Both live in the same JSONB and can shadow each other.

## How updates happen

**Synthesis worker** ([`backend/memory/jobs/synthesis_worker.py:232`](../backend/memory/jobs/synthesis_worker.py#L232)) is the heartbeat. Polls every 5 minutes by default.

For each active user (last messaged ≤30 days):
- **Full synthesis** fires when `generated_at` is older than 02:00 in the user's local timezone. Runs only if there are ≥5 signals (chat + observations + open loops + calendar + graph facts). Calls `synthesize_full_profile()` which is an LLM call that produces the structured narrative, themes, people, etc.
- **Morning refresh** fires at 05:00 user-local. Runs `refresh_morning_digest()` which rewrites only `yesterday` and `today_shape`. Cheaper.
- **Morning proactive trigger** is also called inside this loop ([`synthesis_worker.py:176`](../backend/memory/jobs/synthesis_worker.py#L176)) — that's how the morning ping reaches the user.

**Post-turn extractor hook** ([`backend/memory/hooks/extract_user_facts.py:97`](../backend/memory/hooks/extract_user_facts.py#L97)) fires after every brain turn that ended in `send_burst`. **It does NOT touch `living_profile`** — it writes to a separate `users.facts` JSONB (canonical identity facts like name, role, partner). Different surface.

**Manual** — `update_living_profile` tool exists, brain-callable for direct merges. Rare.

## Where the Living Profile is consumed

1. **Brain prompt** — the most important read site. [`backend/memory/user_facts/rendering.py:139`](../backend/memory/user_facts/rendering.py#L139) `_render_v2_living_profile()` produces a multi-line block:
   ```
   LIVING PROFILE
   <narrative paragraph>

   themes: <running_themes joined>
   people: <key_people one-liners>
   rhythm: <wake_window + first_engage_window>
   read: <emotional_temperature> (<active_tensions>)
   today: <today_shape>
   watch: <watch_for_tomorrow>
   ```
   Most fields make it. The orphans don't.

2. **Dashboard composer** — [`backend/dashboard/compose.py:370-386`](../backend/dashboard/compose.py#L370). Reads only `narrative` + `emotional_temperature`. **No freshness check** — could be using a 24h-stale narrative if the worker stalled.

3. **Morning proactive trigger** — gates fire on `rhythm.typical_first_engage_window`, `watch_for_tomorrow`, plus a "≥3 days of rhythm data" cold-start protection. Reads `narrative + today_shape + watch_for_tomorrow` to draft the message.

4. **`read_situation_brief` tool** — [`backend/memory/tools/read_situation_brief.py`](../backend/memory/tools/read_situation_brief.py). Returns the v1 `situation_brief` (last/this/next week), NOT the v2 narrative. Already auto-rendered into the prompt, so this tool is mostly verification-only. Easy to mistake for the modern read path.

## Production reality

- Env gate is `DONNA_LIVING_PROFILE_REFRESH=1` ([`api/main.py:366`](../api/main.py#L366)).
- The new `donna-synthesis` Railway service we created runs the worker as a standalone process via `DONNA_PROCESS_ROLE=synthesis`, which bypasses the env gate.
- We saw the first tick log in this session: `synthesis_worker: tick swept 1 users`. So **it's running for the first time**.

## Orphans worth deleting from the prompt

- `what_changed_this_week` — synthesized every cycle, rendered nowhere. Wasted Haiku tokens.
- `rhythm.typical_quiet_hours` — written, ignored. Should either feed the proactive arbiter (which currently uses sleep_at/wake_at from `users.facts` instead) or be removed.

## My opinion

This is the most ambitious piece of architecture in Donna. The Living Profile is what makes her feel like she actually knows you, not like she's a stateless chatbot. The structured fields are well thought out — they map to the moves you'd want her to make (`watch_for_tomorrow` → morning trigger, `emotional_temperature` → composer voice).

Two things hurt right now:
1. **Until today, the synthesis worker was never running in prod.** Profiles were stale or unwritten. We just fixed that with the new Railway service.
2. **The dashboard ignores `generated_at`.** A user could see editorial copy based on yesterday's mood. Small, fixable.

**For Donna's vision** — "thinking partner with persistent memory" is the brand. The Living Profile is the memory. If it's stale or empty, Donna is just a polite assistant. If it's fresh, she's the unique thing the doc claims. So getting the synthesis worker running and trimming the orphan fields is core to making her feel like Donna.

## Verdict

Architecture: ✅ ambitious + good
Production: ⚠️ just-now-fixed, needs validation that profiles are actually being written
Gap to vision: medium — it's the load-bearing piece, but it has been load-bearing in name only
