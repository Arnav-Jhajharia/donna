# 01 · Reminders

## What's in the codebase

Two ways a reminder gets created. Both write to the same `donna_schedule` Postgres table.

1. **`attend()` tool** ([donna_runtime/tools.py:2011](../donna_runtime/tools.py#L2011))
   - This is the modern path. The brain calls it whenever the user says anything that should ping them later — "remind me at 6", "wake me up tomorrow", "follow up with maya friday".
   - Goes through [donna/attention/firing.py:273](../donna/attention/firing.py#L273) → `materialize_next_fire` → INSERT into `donna_schedule`.
   - Each row carries `attention_id`, the `recurrence_meta` (so the next fire can be computed), the user's timezone, and a list of WhatsApp messages to send.

2. **`schedule_reminder` tool** ([backend/memory/tools/schedule_reminder.py:79](../backend/memory/tools/schedule_reminder.py#L79))
   - Older path. Same table but no `attention_id`. Just text + fire_at.
   - Still works but `attend` is preferred.

## How firing works

One worker drains the table. [`backend/memory/jobs/schedule_worker.py:454`](../backend/memory/jobs/schedule_worker.py#L454)

- Polls every 5 seconds, batch of 25 rows.
- Locks each row (`status=running`, `locked_at`, `locked_by`) so two workers can't double-fire.
- If `attention_id` is set → routes through dispatcher (gated mode) or `fire_attention_via_brain` (mirror mode, the default).
- If no `attention_id` → renders the queued messages and sends WhatsApp directly.
- After success: writes a `ChatMessage` with `is_proactive=True`, marks `fired=True`, releases lock, queues the next recurrence.

## Snooze, cancel, mark-done

- **Snooze** — `snooze_attention` tool → `snooze_pending_fires` (firing.py:347). Adds N seconds to `fire_at`. Works.
- **Cancel** — `cancel_attention` tool → `cancel_pending_fires` (firing.py:326). DELETEs unfired rows. Works.
- **Mark-done** — no standalone tool. Happens automatically when the worker successfully sends.

## What's actually running in production

**Status: ✅ DEPLOYED 2026-04-28** — `donna-reminders` Railway service (id `d88882f5-3b48-4d69-8f01-49630a09e8cf`) is live on `phase-1-usable`, polling every 5s, batch=25, `/health` passing.

Boot logs confirmed:
```
reminders worker starting (poll=5.0s, batch=25)
db.migrations: donna tables created
```

- The api Railway service does NOT spawn the schedule worker. It deliberately gates on `_api_owns_inprocess_workers()` and shows a log line saying "workers run as standalone scripts."
- `bin/start.sh` routes `DONNA_PROCESS_ROLE=reminders` to `scripts/run_schedule_worker.py` — that script also serves `/health` on `$PORT` so Railway's default healthcheck passes.
- The new `donna-reminders` service runs that role with the full env cloned from `donna` (49 vars) + DONNA_PROCESS_ROLE override.

Effect: every existing queued `DonnaSchedule` row whose `fire_at` is now in the past will start firing within one poll cycle. New rows from `attend()` and `schedule_reminder` deliver normally. Attention LIVE fires (which depend on this same worker) now actually reach the user.

The earlier `zealous-perception` empty stub is unaffected and can be deleted later for cleanliness.

## My opinion

This is the single highest-leverage gap in the entire system right now. The architecture is good — the table, the firing path, the recurrence math, the lock-based concurrency, the brain re-entry hook are all done well. The wiring to a Railway service is the only missing piece, and it's a 30-second fix using the same pattern we used for `donna-attention` and `donna-synthesis`.

**For Donna's vision** — Donna is supposed to be a thinking partner that holds things for you. The whole "she remembers, she follows up" promise breaks the moment you realize her reminders go to /dev/null. This is the most damaging silent failure in the codebase. Fix immediately.

## Risks worth flagging

1. **No alarm on dead worker.** The `last_error` column logs failures but nothing surfaces them. If the reminders service crashes once it's deployed, it'll fail silently again.
2. **60-second lock timeout** could cause duplicate fires under WhatsApp send latency spikes — a second worker steals the lock before the first finishes.
3. **Recurrence on enqueue failure** — if the INSERT for the next fire crashes, that recurring reminder is dead forever.

## Verdict

Architecture: ✅ solid
Production: ✅ live as of 2026-04-28 (see deploy section above)
Gap to vision: closed — pending validation that an actual reminder fires end-to-end through to a real WhatsApp delivery
