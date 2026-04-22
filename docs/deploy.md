# Deploying Donna on Railway

## Stack

- **API service (Railway, Dockerfile)** — FastAPI + Claude Agent SDK. Entry: `api.main:app`.
- **Postgres (Supabase)** — external, keep existing `DATABASE_URL`.
- **FalkorDB (Railway template)** — graph backend for Graphiti, deployed as its own Railway service.

## One-time setup

### 1. Create the Railway project

```
railway login
railway init           # new project
railway link           # or link to existing
```

### 2. Add FalkorDB

Railway dashboard → **New → Database → FalkorDB** (or Redis Stack if FalkorDB template unavailable — FalkorDB is a Redis module, same protocol).

Once deployed, grab its private networking host/port. Typical vars Railway exposes:
- `FALKORDB_HOST` → Railway private hostname (e.g. `falkordb.railway.internal`)
- `FALKORDB_PORT` → `6379`
- `FALKORDB_USERNAME` → usually empty or `default`
- `FALKORDB_PASSWORD` → from the service

Copy those into the API service's env (next step).

### 3. Deploy the API service

From repo root:

```
railway up
```

Railway auto-detects `railway.json` → builds with `Dockerfile` → starts `uvicorn api.main:app --host 0.0.0.0 --port $PORT`.

Health check: `GET /health` on port `$PORT`.

### 4. Set env vars on the API service

Minimum viable set (map from local `.env`):

| Key | Notes |
|-----|-------|
| `ANTHROPIC_API_KEY` | required — model calls |
| `DATABASE_URL` | Supabase pooled URL (`postgresql+asyncpg://...`) |
| `DATABASE_URL_DIRECT` | Supabase direct URL, for migrations |
| `WHATSAPP_TOKEN` | Meta Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta phone-number ID |
| `WHATSAPP_VERIFY_TOKEN` | pick a random string, copy to Meta webhook config |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Meta WABA ID |
| `SUPERMEMORY_API_KEY` | episodic + doc-chunks memory |
| `OPENAI_API_KEY` | used by Graphiti for embeddings/LLM |
| `FALKORDB_HOST` / `FALKORDB_PORT` / `FALKORDB_USERNAME` / `FALKORDB_PASSWORD` | from the FalkorDB service |
| `LANGCHAIN_API_KEY` | LangSmith tracing (optional but recommended) |
| `DONNA_MODEL` | e.g. `claude-haiku-4-5-20251001` |
| `DONNA_REQUEST_TIMEOUT_S` | e.g. `90` |
| `DONNA_TRACE_FILE` | `/tmp/donna_traces.jsonl` — ephemeral; stream to stdout instead if preferred |
| `DONNA_SESSION_STORE` | `/tmp/.donna_sessions.json` — **ephemeral**, see caveat below |

**Do not set** `PORT` — Railway injects it.

### 5. Wire Meta WhatsApp webhook

After Railway assigns a public domain (e.g. `donna-production.up.railway.app`):

1. Meta Developer Console → your app → WhatsApp → Configuration
2. Callback URL: `https://<your-railway-domain>/webhook`
3. Verify token: match `WHATSAPP_VERIFY_TOKEN`
4. Subscribe to `messages` field
5. Verify (Meta calls `GET /webhook` with your verify token; our handler returns the challenge)

### 6. Sanity checks

```
curl https://<domain>/health                          # {"status":"ok"}
# send a real WA message to your business number from the founder phone
# check Railway logs — should show "brain: turn for user=..."
```

## Caveats

### Session store is on local disk

`.donna_sessions.json` lives on the container's filesystem. Railway containers are ephemeral — every redeploy wipes it, and users lose their Claude Agent SDK conversation context (memory layers are unaffected; Postgres + Graphiti + Supermemory survive).

For v1 this is acceptable — a fresh SDK session just reloads the living profile and continues. If that becomes annoying, options:

- Move the session mapping to Postgres (new table `user_sessions`).
- Mount a Railway volume at `/data` and point `DONNA_SESSION_STORE=/data/.donna_sessions.json`.

### Database schema

`api/main.py` startup calls `create_tables()` which runs `metadata.create_all()`. Good for bootstrapping, but **not** for schema changes on an existing DB.

When you need a migration:

```
alembic -c alembic.ini revision --autogenerate -m "..."
alembic -c alembic.ini upgrade head
```

Run migrations from your laptop against `DATABASE_URL_DIRECT` before shipping the new container.

### Bundled Claude Code CLI

The `claude-agent-sdk` wheel ships a platform-specific CLI binary. On Linux (Railway), pip grabs the linux-x86_64 wheel. No Node.js install needed.

### Logs

`uvicorn` logs go to stdout → Railway collects them. Turn logs also persist to `DONNA_TRACE_FILE` — if you don't mount a volume, they're lost on redeploy. Consider setting it to `/dev/stdout` if you prefer everything in Railway's log stream.

## Rollback

Meta webhook cutover is reversible — point the callback URL back at ngrok/previous host. The Railway service can be paused without affecting Supabase or Meta config.

## Cost floor

- Railway API service: ~$5/mo (Hobby) up to actual usage
- Railway FalkorDB: ~$5/mo
- Supabase: existing
- Anthropic, OpenAI, Meta, Supermemory, LangSmith: usage-based, unchanged
