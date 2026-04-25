# Deployment

Donna ships as a single Docker image that runs in one of two roles, selected
at container start time by `DONNA_PROCESS_ROLE`. The currently-supported
topology is:

- **API: local** (your machine, with WhatsApp webhooks reaching it via a
  tunnel like ngrok or Railway-hosted relay).
- **Reminders: Railway**, dedicated service, no BRAIN, just a polling loop
  that fires `DonnaSchedule` rows.

The wire that ties the two is **a single shared Postgres**. Both processes
must point at the same `DATABASE_URL`. The local API writes new schedule
rows; the Railway worker fires them.

## Roles

| Role | Start command (via `bin/start.sh`) | Purpose |
|------|------------------------------------|---------|
| `api` (default) | `uvicorn api.main:app` | Webhook ingress, dashboard backend, BRAIN turns |
| `reminders` | `python scripts/run_schedule_worker.py` | Fires DonnaSchedule rows + tiny `/health` |

The reminders worker:
- Only opens DB + WhatsApp connections.
- Calls `create_tables()` on boot (idempotent — safe even if the API hasn't
  hit this DB yet).
- Serves `GET /health` on `$PORT` so Railway's default healthcheck passes
  unmodified.
- Persists each fired message to `chat_messages` with `is_proactive=True`
  so the next BRAIN turn (running locally) sees it in `RECENT CHAT`.

## Railway service: reminders only

Set up one service in your Railway project pointing at this repo:

1. **Create a new service** from this GitHub repo / branch.
2. **Provision a managed Postgres** in the same Railway project (or use
   Supabase / Neon — anything that gives you a `postgresql://` URL with
   SSL).
3. **Env vars on the reminders service:**

   | Var | Value |
   |---|---|
   | `DONNA_PROCESS_ROLE` | `reminders` |
   | `DATABASE_URL` | Railway Postgres `DATABASE_URL` (use `?sslmode=require`) |
   | `WHATSAPP_TOKEN` | Same Cloud API token your local API uses |
   | `WHATSAPP_PHONE_NUMBER_ID` | Same phone number ID |

   Optional tuning:

   | Var | Default | Notes |
   |---|---|---|
   | `DONNA_REMINDERS_POLL_S` | `5.0` | Seconds between DB polls |
   | `DONNA_REMINDERS_BATCH` | `25` | Max rows fired per tick |

4. **Healthcheck:** leave the default `/health` from `railway.json` — the
   worker serves it.
5. **Networking:** the service does NOT need a public domain. It only
   makes outbound calls (DB + WA Cloud API).
6. **Deploy.** Railway will build via `Dockerfile`, run `bin/start.sh`,
   see `DONNA_PROCESS_ROLE=reminders`, and start the worker.

## Local: API only

Your local machine runs the API. Reminders are NOT fired locally — Railway
handles that.

```sh
# .env (local) — point at the SAME Postgres Railway uses
DATABASE_URL=postgresql+asyncpg://...railway...?sslmode=require
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
ANTHROPIC_API_KEY=sk-ant-...
# ...other API-side vars (Supermemory, Composio, etc.)

# Run the API
uvicorn api.main:app --reload
```

Expose it to Meta via ngrok (or whatever tunnel you use today) so WhatsApp
webhooks hit your laptop. Donna's BRAIN runs locally; when it calls
`schedule_reminder`, the row lands in the shared Postgres and Railway picks
it up at fire time.

## Persistence after fire

When a reminder fires successfully, the worker:
1. POSTs each rendered message to the WhatsApp Cloud API.
2. Writes one `chat_messages` row per renderable message (`role="assistant"`,
   `is_proactive=True`), with text from `render_outbound_text`.
3. Marks the `DonnaSchedule` row `fired=True, status="done"` in the same
   transaction as the chat rows.

Your local API loads recent chat history from the shared `chat_messages`
table on the next inbound, so the BRAIN sees the reminder Donna sent
without needing to query `donna_schedule`.

## Sanity check checklist

Before deploying:

- [ ] Local `.env` and Railway env both have the same `DATABASE_URL`.
- [ ] Local `.env` and Railway env have the same `WHATSAPP_TOKEN` /
      `WHATSAPP_PHONE_NUMBER_ID` (otherwise the reminder fires from a
      different sender than the conversation).
- [ ] Railway service has `DONNA_PROCESS_ROLE=reminders`.
- [ ] Local API does NOT have `DONNA_PROCESS_ROLE=reminders` (defaults
      to `api`).
- [ ] You can hit the Railway service `/health` and it returns
      `{"status":"ok","role":"reminders"}`.
- [ ] After a test reminder fires, `select * from chat_messages where
      is_proactive=true order by created_at desc limit 1;` shows the row.
