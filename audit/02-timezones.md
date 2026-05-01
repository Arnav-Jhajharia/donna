# 02 · Timezones

## How timezones get captured

- The brain calls `remember(kind='timezone', timezone='<IANA>')` which lands in [`backend/memory/tools/set_timezone.py:97`](../backend/memory/tools/set_timezone.py#L97).
- This writes the IANA string (like `Asia/Mumbai`) into `users.timezone`, mirrors it into `users.facts.current_timezone`, and records a bitemporal "user said their timezone was X on date Y" fact.
- A scaffolded path exists in [`donna_runtime/context_builder.py:573`](../donna_runtime/context_builder.py#L573) for the brain to ask "what's your timezone?" when missing — this fires a TIMEZONE CHECK block in the system prompt.

## Default

If nothing is set, everything falls back to `Asia/Singapore`. This is hardcoded in:
- [`db/models.py:28`](../db/models.py#L28) — User table column default
- [`donna/attention/normalize.py:40`](../donna/attention/normalize.py#L40) — UserContext default
- [`backend/memory/time.py:13`](../backend/memory/time.py#L13) — `DEFAULT_TIMEZONE` constant

## Library

`zoneinfo.ZoneInfo` (Python stdlib, DST-aware). No `pytz`. Imports are consistent across `firing.py`, `set_timezone.py`, `context_builder.py`, `morning.py`.

## Where timezones are read correctly

These all do the right thing — pass user's TZ in, compute in user's local clock:

- **Schedule firing** — [`donna/attention/firing.py:42`](../donna/attention/firing.py#L42) `compute_next_fire(cadence, after, tz)` — recurrence rules respect user's local time. Cron expressions parsed in user's ZoneInfo.
- **Brain prompt context** — [`donna_runtime/context_builder.py:556-557`](../donna_runtime/context_builder.py#L556) — exposes `timezone:` and `local_time:` lines so the LLM knows what time the user is reading the message.
- **Dashboard composer brief** — same builder, same TZ-aware path.
- **Morning proactive trigger** — [`backend/web/proactive/triggers/morning.py:215-244`](../backend/web/proactive/triggers/morning.py#L215) — engage window checked in user's local time.
- **`resolve_time_expression` tool** — [`backend/memory/tools/resolve_time_expression.py:175-200`](../backend/memory/tools/resolve_time_expression.py#L175) — when user says "tomorrow at 6pm" this tool parses it in their TZ and rolls to next day if past.
- **Calendar/observation rendering in TODAY block** — formats local timestamps.

## Where it's broken

Three real bugs:

1. **Calendar ingest strips timezone info.** [`backend/integrations/calendar_ingest.py:37`](../backend/integrations/calendar_ingest.py#L37) does `dt.replace(tzinfo=None) if dt.tzinfo else dt`. Google sends events with their original TZ; we lose it. Result: all-day events and events on DST boundaries can render on the wrong day.
2. **Today's calendar window is server-UTC, not user-local.** [`donna_runtime/context_builder.py:217`](../donna_runtime/context_builder.py#L217) does `until = now + timedelta(hours=24)` from server `now`. A user in UTC+8 sees their next 24 hours starting 8 hours late.
3. **Morning trigger has no TZ → falls back to UTC.** [`morning.py:215-217`](../backend/web/proactive/triggers/morning.py#L215) — for a user with no timezone set, the trigger fires at 5am UTC. Probably nobody is awake then.

## Other gaps

- **No phone-prefix inference.** A user with `+91...` could be auto-mapped to `Asia/Kolkata`. We don't do this. Every new user defaults to Singapore.
- **Trace timestamps are server-local.** [`donna_runtime/tracing.py:55`](../donna_runtime/tracing.py#L55) uses `datetime.now()` — fine for ops, but if the deployment moves regions, log audit gets confusing.

## DST handling

Tested explicitly. [`backend/tests/test_timezones.py:25-30`](../backend/tests/test_timezones.py#L25) verifies the US spring-forward day computes day boundaries with the post-DST offset. Stored fire_at is naive UTC; TZ string is preserved in `recurrence_meta.user_tz` so re-enqueue uses the right offset.

## My opinion

The timezone system is the most disciplined piece of plumbing in the codebase. Almost everywhere user-facing computes in user-local. The bugs that exist are at the edges (calendar ingest, today window, fallback to UTC), not the core.

**For Donna's vision** — Donna lives on WhatsApp across countries. A user in Mumbai shouldn't get her morning briefing at 9am Singapore time. Fixing the calendar TZ strip and the today-window UTC bug would make her actually feel local. The defaults problem is more about onboarding polish than core function — most users will set their TZ in the first turn.

## Verdict

Architecture: ✅ disciplined
Production: ⚠️ three correctable bugs
Gap to vision: minor (compared to reminders)
