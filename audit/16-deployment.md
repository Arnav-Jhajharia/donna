# 16 — Deployment

The honest, end-to-end story of how Donna runs in production today. Branch `phase-1-usable`, audited 2026-04-28.

## 1. Containerization

One Dockerfile, four roles. `Dockerfile` is plain `python:3.13-slim`, installs `requirements.txt` plus a few pinned extras (`anthropic`, `alembic`, `supermemory`, `graphiti-core[falkordb]`, `openai`), copies the repo, exposes 8000, and hands off to `bin/start.sh`.

`bin/start.sh` is a small case statement on `DONNA_PROCESS_ROLE`:

- `api` → `uvicorn api.main:app`
- `reminders` → `scripts/run_schedule_worker.py`
- `attention` → `scripts/run_attention_worker.py`
- `synthesis` → `scripts/run_synthesis_worker.py`

Same image, four entrypoints. That's the whole trick. `.dockerignore` strips `tests/`, `node_modules`, traces, and venvs so the image stays lean.

## 2. Railway services

Project `abundant-vision`. What's actually running:

- **donna** — the API. `DONNA_PROCESS_ROLE=api`. `/health` is green. This is the WhatsApp brain.
- **donna-attention** — new. Runs `run_attention_worker.py`. Awareness scoring loop.
- **donna-synthesis** — new. Runs `run_synthesis_worker.py`. Living Profile rebuild.
- **FalkorDB** — Graphiti's graph backend. Other services reference it via cross-service env (`FALKORDB_HOST` etc).
- **zealous-perception** — empty stub from a botched earlier reminders attempt. Should be deleted.
- **No `donna-reminders` service.** Nothing fires `DonnaSchedule` rows in prod.

That's the gap. `bin/start.sh` knows how to be `reminders`. Nothing on Railway runs it.

## 3. Branch reality

The `donna` Railway service was tracking `main`. Main has been broken since 2026-04-25 because of a missing `set_image_prompt_hash` import (commit `1f454ef` fixed it on `phase-1-usable` but never landed on main). So we retargeted Railway's deploy trigger to `phase-1-usable` and pushed a 380-file bundle commit (`3349747 chore: bring working tree in sync to unblock prod deploy`) to unstick the deploy.

Translation: prod is now diverged from main on GitHub. Anyone reading main thinks they're reading what's deployed; they're not.

Yes, `phase-1-usable` should be merged to main. Soon. Otherwise the divergence keeps growing, every new branch off main starts with a broken import, and the next person to touch the deploy config will be confused. Land it.

## 4. Vercel / Next.js dashboard

`dashboard/web/vercel.json` is two lines: `{ "framework": "nextjs" }`. Vercel handles the rest. Deployed, yes. Subdomain — Vercel default for the project; not on a custom Donna domain yet.

## 5. Environment variables

The `donna` service carries 49+ vars. The shape, not the values:

- **LLM** — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- **Telephony / messaging** — `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, webhook verify token
- **Integrations** — `COMPOSIO_API_KEY`, `COMPOSIO_GOOGLE_AUTH_CONFIG_ID`, `GOOGLE_*`
- **Search / research** — `EXA_API_KEY`
- **Voice (server side)** — `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY`
- **Storage** — `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
- **Vector / cache** — `QDRANT_URL`, `REDIS_URL`
- **Graph** — `FALKORDB_HOST`, `FALKORDB_PORT`
- **DB** — `DATABASE_URL` (Postgres)
- **Observability** — `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=donna-dev`
- **Role/feature flags** — `DONNA_PROCESS_ROLE`, plus a sea of `DONNA_*` toggles

Worker services inherit a subset. Nothing is rotated on a schedule.

## 6. Database

Postgres on Railway. Migrations live at `backend/db/migrations/versions/0001..0012` (initial tables → bitemporal facts → image events → integrations → proactive pings → schedule/attention link → attentions → dashboard manifests → auth OTPs → integration redirect → open loops due_at → proactive engine v1).

Migrations are **not** auto-applied via Alembic at boot. `api/main.py` startup calls `db.migrations.create_tables()` — a SQLAlchemy `create_all`-style helper. That works for fresh tables but does not run Alembic upgrades. In practice schema drift is handled by running migrations manually before deploy. Race risk: if multiple workers boot simultaneously against a fresh DB, they all try to `create_tables()`. Idempotent in theory, ugly in logs in practice.

## 7. Worker process model

`api/main.py:_api_owns_inprocess_workers()` is the gate. It returns True only when `DONNA_PROCESS_ROLE` is unset or `api`. When the role is `synthesis`, `attention`, or `reminders`, the API process refuses to spawn the in-process worker tasks. That matches `bin/start.sh` — exactly one process owns each loop.

The standalone scripts (`scripts/run_synthesis_worker.py`, `run_attention_worker.py`, `run_schedule_worker.py`, `run_all_workers.py`) are thin wrappers over `run_forever`-style coroutines in `backend/memory/jobs/`. Clean separation. The dev box can still run `run_all_workers.py` to get one-process-does-everything.

## 8. Observability

LangSmith is wired (`donna_runtime/langsmith_tracing.py`, `LANGSMITH_PROJECT=donna-dev`). It's gated by `LANGSMITH_API_KEY` being present and the `langsmith_enabled` setting in `donna_runtime/config.py`. In prod the key is set, so traces flow — to a project literally named `donna-dev`. Rename to `donna-prod` and stop writing dev and prod traces into the same bucket.

Beyond LangSmith: local jsonl trace files (`donna_traces.jsonl`, `donna_gate.jsonl`) are written on the container's ephemeral disk and lost on redeploy. No log aggregation (no Datadog, no Logtail, no Sentry). No alerting. Railway's built-in log viewer is the only post-mortem tool.

## 9. CI/CD

None. `.github/` contains exactly `FUNDING.yml`. No GitHub Actions, no test runs on PR, no lint gate, no migration check, no pre-commit hook (`.pre-commit-config.yaml` does not exist). Railway watches the branch and ships on push. Tests exist (`backend/tests/`, `tests/`) but they only run when someone runs them locally.

## 10. Domain + ingress

Donna serves at `donna-production-c7eb.up.railway.app`. WhatsApp's webhook points there. No custom domain — `donna.ai` (or whatever) is not yet attached. A Railway-generated subdomain in a webhook config is fine for early users; it's also the reason any platform migration becomes a webhook re-registration dance.

## 11. Voice service

`donna-voice/` is its own Python package with its own `Dockerfile` and `railway.toml`. It runs `python -m donna_voice.agent start`, registers with LiveKit Cloud, and waits for SIP dispatches from a Twilio Elastic SIP trunk pointed at `+1-415-423-2657`. Stack: Deepgram STT → LiteLLM proxy → Sonnet 4 → Cartesia TTS → Supabase voice_calls table. Phase 1 deployed; Phase 2 (per-turn calls into the BRAIN node) deferred. So today voice has its own LLM persona, not Donna's memory. It works, it just isn't her yet.

## 12. Dashboard auth flow

There is no email service. Magic links are sent **over WhatsApp** by Donna herself — that's the entire delivery mechanism. The OTP page even calls it out: "text donna for a magic link." No Resend, Postmark, or SES. Less surface area, fewer keys to rotate, one less vendor. Good call for a WhatsApp-native product.

## 13. Production gaps and risks

- No `donna-reminders` service. `DonnaSchedule` rows do not fire in prod.
- `schedule_worker` dispatcher running in mirror mode → `ProactivePing` rows aren't being written; the new proactive engine sees an empty inbox.
- `phase-1-usable` ≠ `main`. The git history of record is on the branch nobody reviews.
- Many `DONNA_*` flags unset (`DONNA_PROACTIVE_TIERED`, `DONNA_ATTENTION_SCHEDULER`, `DONNA_SPAWNERS`). Production behavior depends on which are toggled, and there is no single source of truth.
- `create_tables()` on every worker boot races on a fresh DB. Idempotent but noisy.
- Zero alerting. If `donna-synthesis` crash-loops, nobody knows until the Living Profile goes stale and it shows up in conversation.
- `LANGSMITH_PROJECT=donna-dev` in prod. Prod and dev traces live in one bucket.
- `zealous-perception` ghost service still in the Railway project.

## 14. Opinion

Scrappy, but honest scrappy. The shape is right: one image, role-switched, four workers, deterministic ingress, FastAPI in front, FalkorDB + Postgres + Supermemory behind, Vercel for the dashboard, LiveKit for voice. That's a coherent diagram.

The execution has the fingerprints of a startup mid-pivot. Reminders worker missing. Trace project named `dev`. Webhook on a Railway subdomain. No CI. Magic links over WhatsApp because building email plumbing wasn't worth the morning. Manual migration runs. A production branch that isn't main.

For a thinking-partner-AI shipped to one user, this is fine. For ten users, it's dangerous. For a hundred, it falls over.

The polish gap isn't architectural — it's operational. The model split is right; the ops glue is missing.

## 15. Verdict

- **Architecture:** 8/10. Single image, role-switched workers, in-process gate, deterministic startup. Clean.
- **Production:** 5/10. Right shape, missing piece (reminders), no CI, no alerting, branch drift, manual migrations, dev trace project.
- **Gap to vision:** moderate. To match a thinking-partner-AI level of polish — alerting, custom domain, prod LangSmith project, reminders service deployed, main as source of truth, automated migrations, schema-checked deploys. Two focused days, not two weeks.
