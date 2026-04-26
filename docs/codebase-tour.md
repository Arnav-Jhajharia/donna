# Codebase Tour (How To Learn This Repo)

This is a practical reading order for understanding the live Donna pipeline,
plus the memory and scheduling layers we built around it.

Goal: you can explain "what happens" for any WhatsApp message, and you know
where timezones, memory, and reminders can go wrong.

## Tour Order (Suggested)

1. `api/main.py`
   - webhook ingress, durable inbox, per-phone cancel/restart, save chat rows,
     call brain, send WhatsApp, mark processed
2. `api/graph.py`
   - phone->user lookup, timezone guess, tz confirmation flags (`_tz_done`)
3. `ingress/node.py`
   - reply-to resolution and URL excerpt fetching (context amplification)
4. `donna_runtime/brain.py`
   - runtime context injection + SDK session resume + capture outbound buffer
5. `donna_runtime/context_builder.py`
   - what exactly the model sees as "Runtime Context" (including timezone check)
6. `donna_runtime/runner.py`
   - Claude Agent SDK query loop, tool calls, tracing, terminal invariant
7. `donna_runtime/tools.py` + `donna_runtime/tool_logic.py`
   - what tools the model can call and what each actually does
8. Memory: `backend/memory/time.py`
   - naive UTC storage convention + local calendar bounds + formatting
9. Memory: `backend/memory/tools/log_observation.py` + `backend/memory/tools/list_observations.py`
   - how trackers are stored/retrieved with correct local "last_week"
10. Timezone writes: `backend/memory/tools/set_timezone.py`
   - updating `users.timezone` and marking onboarding tz_done
11. Reminders: `backend/memory/tools/schedule_reminder.py` + `backend/memory/jobs/schedule_worker.py`
   - write schedule rows and how they get delivered later
   - the worker runs as a **separate Railway service** (not inside the API),
     dispatched by `bin/start.sh` when `DONNA_PROCESS_ROLE=reminders`. After each
     successful send it persists the rendered text to `chat_messages` with
     `is_proactive=True` so the next BRAIN turn has context.

## How To Read (Workflow)

- Read one file top-to-bottom.
- For each function: answer 3 questions:
  - Inputs: where does data come from?
  - Side effects: DB writes? network? queues?
  - Outputs: who consumes it next?
- After each file, run `rg` on the primary function name to see callers.

## What Not To Do

- Don't try to understand every file in alphabetical order.
- Don't start in `backend/memory/synthesis/*` unless you already understand
  how chat rows and observations get persisted.

