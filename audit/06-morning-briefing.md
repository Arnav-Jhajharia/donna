# 06 — morning briefing

## what this is supposed to be

Donna's canonical proactive moment. The user wakes up, donna pings them once with the day's read — anchored on what she noticed last night and what shape today has. Not a news roundup. Not a calendar dump. One short message that says "here's the one thing that matters this morning."

## what's actually there

**The trigger** — `backend/web/proactive/triggers/morning.py`
- `maybe_fire_morning_check_in(user_id, timezone_name, living_profile, ...)` at line 197
- Gates, in order: cold-start (`_MIN_RHYTHM_DAYS = 3`, line 35), engage-window (`typical_first_engage_window` ± 30 min fudge, line 41), `watch_for_tomorrow` non-empty (line 228), idempotency stamp `morning_proactive_last_fired_at` (line 105–117), phone exists (line 240).
- All gates pass → builds a short proactive prompt (`_build_prompt`, line 120) → calls `donna_turn` in `mode="proactive"` → reads `_outbound` from result → ships via `WhatsAppChannel.send_many` → persists `morning_proactive_last_fired_at` so it can't fire twice today.
- Returns `MorningTriggerDecision(fired, reason)` so tests and traces can see exactly which gate let it through or which closed it. Reason vocabulary: `fired | outside_window | no_watch | cold_start | already_fired_today | no_phone`.

**The synthesis that feeds it** — `backend/memory/synthesis/living_profile.py`
- `synthesize_full_profile(user_id)` (line 547) — full nightly Haiku pass at 02:00 local. Reads chat (14d, 80 msgs), observations (30d, 60 rows), open loops, calendar (±7d), Graphiti facts (4 themed queries × 8 each). Writes the full v2 profile — narrative + running_themes + situation + tensions + people + what_changed_this_week + watch_for_tomorrow + emotional_temperature + rhythm + yesterday + today_shape.
- `refresh_morning_digest(user_id)` (line 601) — cheaper Haiku pass at 05:00 local. Only regenerates `narrative`, `yesterday`, `today_shape`. Merges back into the existing JSONB without disturbing watch_for_tomorrow / rhythm / key_people / running_themes.
- Both write to `users.living_profile`. `generated_at` and `yesterday_refreshed_at` are the idempotency stamps.

**The morning prompt** — `backend/memory/synthesis/prompts/living_profile_morning.md`
- Tells the model: not Donna talking to user, internal pass. Narrative is THE primary field (240–420 chars). Plain declarative sentences. No psychological diagnoses, no metaphors, no em dashes. Yesterday and today_shape are sidecars.
- This is the right stance — situational, not interpretive. Donna brings the read at turn time.

**The worker** — `backend/memory/jobs/synthesis_worker.py`
- `run_forever()` polls every 5 min (line 50). Each tick lists active users (last 30d active, line 109), checks `is_full_due` and `is_morning_due` per user (lines 83, 95), runs the right synthesizer.
- After synthesis, regardless of whether either ran, it ALSO calls `maybe_fire_morning_check_in` (line 175–186). The trigger has its own gates so this is safe to call every tick — most ticks fail at "outside_window" or "already_fired_today" cheaply.

**Deployment** — `scripts/run_synthesis_worker.py`
- Standalone script. Launched when `DONNA_PROCESS_ROLE=synthesis`. The API process explicitly does NOT spawn it (api/main.py:322–348).
- Serves a tiny `/health` if `PORT` is set so Railway's healthcheck passes.

**Outbound shape** — single short message via `send_burst`. Not a "burst" of multiple messages, not a dashboard push. The brain runs one proactive turn, decides what to say (or stays silent), and ships through the normal `_outbound` buffer. Memory hooks fire on the burst (`is_proactive=True` chat row).

**Dashboard recompose at morning** — there is none. `compose_manifest` has a `moment` field (dawn / morning / midday / ...) inferred from local time, and the dashboard plans library has `morning-aarav.ts`, `morning-after-bad-day.ts`, `busy-pitch.ts` as morning shapes — but nothing in the morning trigger calls `update_dashboard` or `compose_manifest`. The brain *could* call `update_dashboard` during the proactive turn since it has the tool, but nothing forces it.

## what works vs what's broken

**Works:**
- All five gates are clean, unit-testable, and have tests in `backend/tests/test_morning_trigger.py`.
- Idempotency is real — it survives restarts because the stamp lives in Postgres, not memory.
- Cold-start protection is honest — `_rhythm_data_days` doesn't pretend to know more than it does (line 80).
- Worker / API split is clean. The reminders/synthesis split commits (3349746, c86116d, 4524929) finally got the synthesis worker its own service.
- Synthesis itself is high-quality. Narrative-primary is the right call.

**Broken / missing:**
- The morning trigger reads `living_profile` from a snapshot the worker took before the synth ran. Comment at line 180 says "Re-read profile in case morning_runner just refreshed it" — but the code doesn't actually re-read; it passes the same `profile` dict that was loaded in `_list_active_users`. So on the very tick that morning digest refreshes, the trigger sees stale watch_for_tomorrow. Next tick (5 min later) is fine, but it's a subtle bug. File: `backend/memory/jobs/synthesis_worker.py:181`.
- `morning_proactive_last_fired_at` is persisted on the User row inside the trigger module, separately from how synthesis stamps the same JSONB. Two writers to one JSONB without serialization — a race is possible if a synth pass and a trigger fire land on the same user in the same tick. Unlikely with current concurrency (sem=4) but real.
- No "evening briefing" counterpart exists. The system has the data — `synthesize_full_profile` runs at 02:00 local, which is the de-facto evening recap moment (yesterday object freshly written). But nothing pings the user at 22:00 local with "here's how today went, here's what tomorrow looks like." Several dashboard plans imply it (the `late` / `evening` moment shapes exist), but no trigger.
- The dashboard is not recomposed at morning. The user opens it cold. The brain has `update_dashboard` as a tool and the morning trigger runs the brain — but the prompt at line 138–142 says "fire ONE short proactive message" and never mentions the dashboard. So in practice the brain ships text and the dashboard stays as last-composed.
- `_rhythm_data_days` proxy (line 80) is a heuristic. It's honest about that, but it means a user who messages a few times in a single day can clear the cold-start gate prematurely. Should bind to a real `data_days` int that synth populates — there's a TODO baked into the code.

## opinion — does this match Donna's vision

Yes — and it's one of the more honest pieces of the system.

The vision is "thinking partner with persistent memory, high-agency, lowercase." Morning briefing as currently shaped is exactly that:
- It uses memory she actually has (the watch_for_tomorrow that yesterday's synth produced — a real signal, not a generic horoscope).
- It earns the interrupt. The watch must be non-empty AND the rhythm must be > 3 days established AND the user must be in their typical engage window. Three independent "is this earned" gates.
- It can stay silent. The brain's prompt explicitly says "if there's nothing meaningful to say, end the turn with stay_silent."
- It's anchored in user-specific signal, not boilerplate.

This is right. The wrong shape would be a daily horoscope ("good morning, today you have 3 meetings, the weather is sunny") — Donna doesn't do that. The current shape is "I noticed X yesterday, here's the one thing for this morning."

**Should the dashboard be recomposed at morning too?** Yes. This is a clear miss. The user wakes up, gets the WhatsApp ping, opens the dashboard from the persistent link in their phone — and the dashboard shows whatever was composed last (could be 18 hours stale). The right move is to have the morning trigger call `compose_manifest(trigger="morning_check_in")` *before* the brain runs, or have the brain prompt include "after your message, call update_dashboard." The data is fresh (synth just finished), the dashboard composer reads `living_profile.narrative` and `today_shape` — it would land. This is a one-line fix and an obvious win.

**Is the content good?** The content is right in shape (anchor on watch_for_tomorrow, one thing, terse). The risk is `watch_for_tomorrow` being weak. It's a Haiku output, sometimes empty, sometimes generic. The `no_watch` gate handles emptiness. Genericness is harder. Worth eval-tracing the watch field over a week of real users to see if it's actually delivering specific anchors or fallback platitudes.

## verdict

- **Architecture: 9/10** — Clean separation. Trigger module is its own thing, separate from the Exa research runner. Gates are testable. Idempotency is real. Voice prompt is right.
- **Production: 7/10** — Was orphaned until ~2026-04-25. Just got its dedicated Railway service via `DONNA_PROCESS_ROLE=synthesis`. There's a stale-profile-by-one-tick bug, a JSONB race window, and the dashboard isn't recomposed in lockstep. But the core path runs.
- **Gap to vision: small** — Morning briefing is one of the few things in this codebase where what's built matches what the vision asks for. Add the dashboard recompose, harden the data_days signal, and add an evening counterpart, and this is a flagship behavior.
