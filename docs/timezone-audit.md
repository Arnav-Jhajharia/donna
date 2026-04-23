## Timezone Audit (Reminders, Scheduling, Attention, Memory)

This repo uses "naive UTC in Postgres" as the storage convention for most timestamps.
The product contract (in `donna_runtime/prompt.py`) is stronger: user-facing times
should always be rendered in the user's timezone, and time-bounded queries ("this week",
"today") should be evaluated in the user's local calendar boundaries.

This doc inventories current behavior and the main timezone failure modes.

### Canonical Timezone: What We Have Today

- Canonical operational timezone is `users.timezone` (string IANA TZ).
  - Set on user creation by phone-prefix guesser in `api/graph.py`.
  - Used to prime the runtime prompt: `donna_runtime/context_builder.py` renders
    `timezone:` and `local_time:` for the model based on `state["_user_timezone"]`.
- There is also a "facts" timezone layer:
  - `backend/memory/user_facts/schema.py` defines `home_timezone` and `current_timezone`
    in `users.facts`, but these do not drive scheduling or tool behavior.

Main issue: `users.timezone` is guessed once and appears to have no explicit update path.
If the user travels or the guess is wrong (especially `+1`), the system drifts.

### Where Timezone Is Correct Today

- Turn context "now":
  - `donna_runtime/context_builder.py` computes a local timestamp via `ZoneInfo(users.timezone)`.
- Observations (tracker data):
  - Writes: `backend/memory/tools/log_observation.py` interprets naive timestamps as user-local
    before storing naive UTC (via `backend/memory/time.py`).
  - Reads: `backend/memory/tools/list_observations.py` supports local calendar periods
    (`today`, `yesterday`, `this_week`, `last_week`) and returns `event_time_local`.
- Calendar reads:
  - `backend/memory/tools/list_calendar.py` returns `start_time_local`/`end_time_local`
    (but see query-boundary caveats below).
- Temporal "situational brief" bucketing:
  - `backend/memory/synthesis/temporal_brief.py` uses `users.timezone` week boundaries
    for last/this/next week classification.

### Known Timezone Leaks / Failure Modes

1. Timezone source-of-truth drift
   - `users.timezone` is phone-prefix guessed (`api/graph.py`), not validated.
   - Extracted facts (`users.facts.current_timezone`) are not reconciled back to `users.timezone`.
   - Result: the model sees a wrong "local_time" and all local period bounds become wrong.

2. Reminders and "remind me at 6pm" in Attention are timezone-wrong
   - `donna/attention/author.py` short-circuits bare reminders into a Ping spec with
     `cadence.type=ONE_SHOT` and `trigger_at=_extract_trigger_iso(raw)`.
   - `_extract_trigger_iso` uses `datetime.now(timezone.utc)` and interprets "6pm" as 18:00 UTC,
     not 18:00 in the user's timezone.
   - No timezone is stored on the spec to disambiguate future scheduling.

3. Scheduled cadence (cron) is timezone-ambiguous
   - `donna/attention/schema.py` allows `CadenceType.SCHEDULED` with `params["cron"]`, but
     there is no required `timezone` param.
   - Any cron evaluation will default to server timezone or UTC unless explicitly handled.
   - DST correctness requires evaluating cron in a specific IANA zone.

4. Quiet hours policy cannot be enforced correctly without timezone wiring
   - `donna_runtime/prompt.py` defines quiet hours in user-local time, but there is no
     runtime enforcement layer yet.
   - Any future enforcement needs `users.timezone` (and likely sleep window) to be reliable.

5. Calendar query boundaries are still UTC-based
   - `backend/memory/tools/list_calendar.py` queries `start_time >= utcnow` and `<= utcnow+within_days`.
   - For "today/tomorrow" semantics near midnight, this can exclude/include the wrong events.
   - It also does not expose a local `period` API like observations do.

6. Episodic / graph recall timestamps are not normalized for user display
   - `donna_runtime/tool_logic.py` renders timestamps returned by memory providers as-is.
   - These are likely UTC or provider-specific strings, which violates the prompt contract
     when shown to the user as an absolute time.

7. Message timestamps are ingestion-time, not send-time
   - `chat_messages.created_at` is set by server default (`db/models.py.utcnow()`).
   - If webhook delivery is delayed, week-bucketing and "last week" narratives can be skewed.

### Scheduling State: What Exists vs What Is Wired

- `db/models.py` defines `DonnaSchedule(fire_at, recurrence, context, ...)`.
- There is currently no production code that creates `DonnaSchedule` rows from user requests,
  and no worker that reads due rows and sends them.
- `backend/memory/synthesis/temporal_brief.py` reads `DonnaSchedule` for rendering, but that
  does not imply schedules are being produced/fired today.

### Recommendations (High Leverage)

1. Pick a true timezone authority
   - Make `users.timezone` the only operational source for:
     - all time parsing ("tomorrow 9am"), all scheduling, all "today/this week" queries.
   - Treat `users.facts.(home_timezone/current_timezone)` as narrative/stability data, and
     only sync it into `users.timezone` through an explicit update flow.

2. Add an explicit timezone update flow
   - A small tool/endpoint to update `users.timezone` (and optionally mirror to `users.facts.current_timezone`).
   - For `+1`, guess is often wrong; confirm early (CTA "confirm timezone").

3. Require timezone in Attention cadence params
   - For `ONE_SHOT`: store `trigger_at` as an ISO string with offset OR store `(trigger_at_utc, timezone)`.
   - For `SCHEDULED`: require `params["timezone"]` (IANA) so cron is unambiguous.

4. Centralize time parsing for reminders/schedules
   - Reuse `backend/memory/time.py` patterns: interpret naive timestamps as user-local.
   - Avoid "UTC-now replace(hour=...)" patterns like `donna/attention/author.py:_extract_trigger_iso`.

5. Add a local-period API to calendar reads
   - Mirror `list_observations(period=...)` with `list_calendar(period=...)` for `today`, `tomorrow`, `this_week`.

6. Protect user-facing times in tool renderings
   - Prefer emitting `*_local` fields and timezone labels.
   - Avoid printing raw provider timestamps directly to the user.

### Tests That Catch Real Breakage

- DB-backed boundary tests for:
  - `list_observations(period="last_week")` across SG/NY/London (already exists in `tests/test_integration_end_to_end.py`).
  - `list_calendar(period="today")` near midnight in multiple zones.
- A unit test for Attention reminder extraction:
  - Given user timezone `Asia/Singapore`, "remind me to call mom at 6pm" should produce
    a `trigger_at` that corresponds to 18:00 SG, not 18:00 UTC.

