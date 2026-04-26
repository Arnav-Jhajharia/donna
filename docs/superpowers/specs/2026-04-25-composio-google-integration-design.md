# Composio Google Integration — Calendar + Gmail (v1)

**Date:** 2026-04-25
**Status:** Design
**Owner:** Bharat

## Why this exists

Donna's proactive voice — morning briefings, "I noticed…" pings, ambient
helpfulness — is only as good as what she knows about the user. Today she
knows what's been said *to her*. That's not enough. Gmail and Calendar are
the densest sources of biographical and present-state signal a user already
owns. Wiring them is the unlock.

This v1 covers:

- Auth round-trip via Composio.
- Connection-state primitive Donna sees in her per-turn context.
- Mirror-first sync (Composio webhooks → local Postgres).
- One-time bootstrap that fills `users.living_profile.biography` so Donna
  has a first impression of the user from day zero.

## Non-goals (v1)

- Composio MCP server / tool-search wiring (deferred to a later phase).
- Action tools — send email, create event, modify event, archive.
- Other Google surfaces: Drive, Tasks, Contacts, Maps timeline, Photos.
- Other providers (Microsoft, Slack, Notion, etc.).
- Fan-out of biography output to bitemporal facts, Graphiti, Supermemory.
- Disconnect/delete flow detail (covered at high level only).
- Polling. Webhooks are the source of truth; daily reconcile is defensive.

## Architecture

```
WhatsApp turn
  └─ BRAIN loop
       └─ tool: connect_integration(provider, products)
            └─ Composio Python SDK: get-or-create connection
                 └─ returns OAuth URL → Donna sends via WhatsApp

User taps link → Google OAuth → Composio captures tokens
  └─ Composio webhook → POST /webhooks/composio (auth-complete)
       └─ integrations.status = connected
       └─ enqueue bootstrap jobs
       └─ subscribe live triggers: gmail-new-message, calendar-changed

Live (steady state):
  Composio gmail trigger → webhook → label-router → email_messages mirror
  Composio calendar trigger → webhook → upsert calendar_entries

Daily reconcile (defensive):
  cron pulls last 24h gmail headers + next 14d calendar, fills any gaps

Read path (Donna):
  list_calendar(...)         reads local calendar_entries
  list_gmail_recent(...)     reads local email_messages
  read_gmail_thread(id)      reads local; lazy-fetches body if not stored
```

Hand-written tools sit on top of local mirrors. Composio is touched only
during auth, bootstrap, and live webhook ingest. The brain loop never
makes a synchronous call to Google.

## Components

### `integrations` table (new)

```sql
CREATE TABLE integrations (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         text NOT NULL REFERENCES users(id),
  provider        text NOT NULL,                   -- "google"
  product         text NOT NULL,                   -- "calendar" | "gmail"
  status          text NOT NULL DEFAULT 'pending', -- pending | connected | revoked | expired | error
  composio_connection_id  text,
  connected_at    timestamptz,
  last_synced_at  timestamptz,
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_integrations_user_provider_product
  ON integrations(user_id, provider, product);
```

This is the source of truth for connection state. The `[INTEGRATIONS]`
context block is rendered from rows of this table.

The existing `oauth_tokens` table is repurposed as a fallback / backup
slot for raw token storage if we ever bypass Composio. v1 uses Composio
for token management; we store only the `composio_connection_id`.

### `email_messages` mirror (new)

```sql
CREATE TABLE email_messages (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         text NOT NULL REFERENCES users(id),
  gmail_message_id text NOT NULL,
  thread_id       text NOT NULL,
  from_address    text NOT NULL,
  from_name       text,
  to_addresses    text[] NOT NULL DEFAULT '{}',
  cc_addresses    text[] NOT NULL DEFAULT '{}',
  subject         text,
  snippet         text,
  body_text       text,                             -- nullable; only when label policy says "full"
  body_stored     boolean NOT NULL DEFAULT false,
  labels          text[] NOT NULL DEFAULT '{}',     -- gmail labels incl. PRIMARY/IMPORTANT/STARRED/SENT/etc.
  is_important    boolean NOT NULL DEFAULT false,   -- gmail's IMPORTANT label
  is_starred      boolean NOT NULL DEFAULT false,
  is_sent         boolean NOT NULL DEFAULT false,
  ingest_depth    text NOT NULL,                    -- 'full' | 'metadata' | 'aggregate'
  internal_date   timestamptz NOT NULL,
  ingested_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_email_user_msg UNIQUE (user_id, gmail_message_id)
);
CREATE INDEX idx_emails_user_date ON email_messages(user_id, internal_date DESC);
CREATE INDEX idx_emails_user_important ON email_messages(user_id, is_important) WHERE is_important;
CREATE INDEX idx_emails_user_thread ON email_messages(user_id, thread_id);
```

`body_text` is only populated for `ingest_depth='full'` messages. The
label-routing policy decides depth (see below). Bodies for
`metadata`/`aggregate` rows can be lazy-fetched on demand by
`read_gmail_thread`.

### `calendar_entries` (existing — no schema change in v1)

Already exists with `google_event_id` field. The new sync path writes
into it directly via webhook ingest. No migration; only the writer
changes from "manual" to "webhook-driven."

### `connect_integration` tool

```
name: connect_integration
description:
  Generate a connect link for an external provider. Use when:
    - the user asks for something requiring an integration that is not connected
    - the [INTEGRATIONS] context block shows the integration as not_connected
    - the user explicitly asks to connect something
  Do NOT use when:
    - the integration is already connected (check [INTEGRATIONS])
    - the user is mid-task and a connect prompt would derail them
    - status is "pending" — the user has a link in flight
input_schema:
  provider: enum["google"]
  products: array<enum["calendar","gmail"]>
returns:
  status: "url_sent" | "already_connected" | "pending"
  url: string|null
  message: string  # voice-appropriate one-liner Donna sends as-is or
                   # rephrases; the consent statement (what Donna will
                   # read on first connect) MUST be preserved when sent.
```

The tool is L1 (acts on user data via Composio): no PreToolUse gate
needed because the side effect is just "ask Composio for an auth URL"
which is idempotent. The tool writes/updates an `integrations` row in
status `pending` if not already connected.

The tool returns a URL, not a finished connection. Donna sends the URL
to the user via WhatsApp using the existing `send_burst` terminator. The
voice for the connect message is:

> need gmail + calendar to be useful. one-time read of today's inbox + a sample of important mail to learn who matters to you. tap: <url>

Voice constraints: lowercase, no em dashes, no semicolons, no "I
understand," blunt, includes the consent statement in one breath.

### Composio webhook handler

`POST /webhooks/composio` (added to `backend/web/` — route module to be
created).

Verifies HMAC signature against shared `COMPOSIO_WEBHOOK_SECRET`.

Three event categories:

1. **`connection.complete`** — auth round-trip finished.
   - Update `integrations.status='connected'`, set `connected_at`.
   - Enqueue `bootstrap_gmail(user_id)` and `bootstrap_calendar(user_id)`.
   - Subscribe live triggers via Composio API (idempotent — does nothing
     if already subscribed).

2. **`gmail.new_message`** — single new email arrived.
   - Pass through label-router → store at appropriate depth.
   - Update `integrations.last_synced_at`.

3. **`calendar.event.{created,updated,deleted}`** — calendar event change.
   - Upsert/delete on `calendar_entries`.
   - Update `integrations.last_synced_at`.

Composio trigger names verified at implementation time against current
Composio docs (subject to vendor renaming).

### Label-routing policy (single source of truth)

One pure function, called from both bootstrap and live ingest.

```
classify_depth(labels, is_starred, is_important, is_sent) -> "full" | "metadata" | "aggregate" | "ignore"

  if "SPAM" or "TRASH" or "DRAFT" in labels: ignore
  if is_sent or is_starred or is_important: full
  if "PRIMARY" in labels or no category labels (uncategorized inbox): full
  if "UPDATES" in labels: metadata   # transactional events; subject + sender carry the signal
  if "FORUMS" in labels: metadata    # community memberships = interest signal
  if "SOCIAL" in labels: metadata    # light relationship signal from notifications
  if "PROMOTIONS" in labels: aggregate  # sender frequency only, no body, no per-message row
  user-defined labels: full if heavily used (heuristic deferred), else metadata
```

`full` = body stored. `metadata` = row stored, body nullable, lazy-fetch
on demand. `aggregate` = no row; counted in a separate `email_sender_aggregates`
view (or computed at query time from existing rows). `ignore` = drop.

### Bootstrap pipeline

Triggered from the `connection.complete` webhook. Three stages, run in
sequence per user:

**Stage 1 — dense today:** pull every message with `internal_date` >=
local-midnight that survives `classify_depth != ignore`. Write rows at
classified depth. Typically 5–50 messages.

**Stage 2 — sampled 30d important:** pull messages with `IMPORTANT`
label and `internal_date` >= now − 30d. Full body for each. Typically
20–100 messages.

**Stage 3 — sender-frequency aggregates (last 90d):** for every sender
that appears more than once in the 90-day window, count occurrences and
collect sample subjects. Top 50 senders only. Metadata-only; no bodies
fetched. Stored in a small `email_sender_aggregates` table or computed
at biography-extraction time and discarded.

After all three stages land, run the **biography synthesis** pass:

```
Input:
  - all stage-1 messages (full body)
  - all stage-2 messages (full body)
  - top-50 sender aggregates (counts + sample subjects)

LLM passes (batched, Sonnet 4.6):
  pass A — relationships: extract people. for each: name, relationship
           (colleague|family|friend|vendor|other), frequency, role
           inference, last contact.
  pass B — work: current employer, role, projects, key collaborators.
  pass C — interests: newsletters subscribed, themes, communities.
  pass D — life signals: travel patterns, big purchases, recurring
           rhythms.

Synthesis pass:
  combine into a biography dict; write a 2–3 sentence narrative summary.
```

Output dict shape:

```json
{
  "overview": "<2-3 sentence narrative>",
  "work": {
    "employer": "...",
    "role": "...",
    "projects": ["..."],
    "collaborators": [{"name": "...", "role": "..."}]
  },
  "relationships": [
    {"name": "Sarah", "kind": "colleague", "frequency": "weekly", "last_seen": "2026-04-22"}
  ],
  "interests": ["..."],
  "rhythms": {"work_hours": "...", "travel": "..."},
  "evidence_window": {
    "today_messages": 14,
    "important_30d_messages": 28,
    "aggregated_90d_senders": 50
  },
  "last_bootstrapped_at": "2026-04-25T03:14:00Z"
}
```

Written via the existing `update_living_profile(patch={"biography": <dict>})`
tool — no new write path needed.

### `[INTEGRATIONS]` per-turn context block

**Placement:** the `runtime_context` block assembled in
`donna_runtime/context_builder.py:render_turn_context`, NOT the system
prompt and NOT the `user_model_block`. The system prompt is
deliberately byte-stable for prefix caching (`prompt.py:build_system_prompt`
discards user-specific args). Connection state is volatile — it flips
mid-session when a webhook lands — so it must be re-read per turn from
the `integrations` table and prepended to the user message via
`wrap_user_message_with_context(runtime_context=...)`.

Format:

```
[INTEGRATIONS]
  google_calendar: connected · synced 8m ago
  google_gmail:    connected · synced 2m ago
```

Alternative states render as:
- `not_connected` — Donna can offer to connect when relevant.
- `pending` — link is in flight. Donna does not nag a second link.
- `revoked` — the user disconnected. Donna acknowledges and stops trying.
- `expired` — refresh failed. Donna offers a reconnect.
- `error: <short>` — operational error. Donna mentions degraded mode if asked.

≤5 lines under any non-pathological state. Sourced from a single
`SELECT` against the `integrations` table per turn. Cheap.

### Biography renderer extension

**Placement:** the `user_model_block` (composed by
`backend/memory/user_facts/rendering.py:load_and_render`), which is
prepended to the user message at turn time alongside `USER MODEL` and
`SITUATION BRIEF` / `LIVING PROFILE`. Same path as today; we only add
one new section.

Extend `render_living_profile_block` to surface a `BIOGRAPHY` section
under the existing `SITUATION BRIEF` and `LIVING PROFILE` sections.
Reads `profile.get("biography")`. Renders a compressed view — narrative
summary + 2-3 lines for work, top 3-5 relationships, 2-3 interests.

The full biography dict can grow large; the rendered block is bounded
to keep prompt size predictable. Deeper retrieval into the biography
(e.g. "tell me about Sarah") goes through a separate retrieval tool
call, not the always-included render.

### Read tools (additions)

**`list_gmail_recent(within_hours, limit, important_only=false)`**
- Reads `email_messages`. Returns thread snippets sorted by recency.
- when-NOT: when the user's question is about a *specific* thread or
  sender — use `read_gmail_thread` or filter via the next iteration.
- v1 keeps signature minimal; future: sender filter, label filter.

**`read_gmail_thread(thread_id)`**
- Returns full thread bodies for one thread.
- If a row exists with `body_stored=false`, lazy-fetch the body via
  Composio, persist, return.
- when-NOT: for triage-level questions; use `list_gmail_recent`.

`list_calendar` already exists and reads from `calendar_entries`. No
changes for v1; behavior continues unchanged once the mirror is being
populated by webhooks.

### Daily reconcile (defensive)

Cron at 03:30 local TZ per user. For each connected integration:

- Calendar: pull `next 14 days` events, diff against `calendar_entries`,
  upsert missing.
- Gmail: pull `last 24h` headers, diff against `email_messages`, ingest
  any missing (apply label-routing).

Webhooks remain the source of truth; reconcile only fixes drift from
missed deliveries.

## Data flows

### First-connect happy path

1. User asks "what's on my calendar today?"
2. Donna sees `[INTEGRATIONS] google_calendar: not_connected`.
3. Donna calls `connect_integration(provider="google", products=["calendar","gmail"])`.
4. Tool fetches Composio auth URL, writes integrations row(s) `status=pending`.
5. Donna's reply burst includes the URL with the consent line.
6. User taps, OAuths through Google, Composio captures tokens.
7. Composio fires `connection.complete` webhook.
8. Handler updates `status=connected`, enqueues bootstrap jobs, subscribes triggers.
9. Bootstrap stages 1–3 run; biography synthesized; `users.living_profile.biography` patched.
10. Live triggers begin firing on new messages / events.
11. On the user's next turn, `[INTEGRATIONS]` shows `connected · synced Xs ago` and the rendered `BIOGRAPHY` block is in the system prompt.

### Disconnect / revoke

Composio fires `connection.revoked` (name TBV). Handler sets
`status=revoked`. v1 keeps mirror data in place (no cascade delete) but
stops accepting new webhooks. Optional disconnect-and-purge is a
separate user-initiated tool — out of v1 scope. Documented as a
follow-up.

## Voice

- Connect message (Donna composing on the fly, not a fixed string):
  > need gmail + calendar to be useful. one-time read of today's inbox + a sample of important mail to learn who matters to you. tap: <url>

- Bootstrap completion (deferred — out of v1): a single proactive ping
  with one observation Donna picked up. Not in v1; v1 quietly populates
  biography and waits for the user's next turn.

- Connection lost: when Donna detects a `revoked` or `expired` state in
  context for the first time after a successful connect, she may
  surface it briefly: "gmail's disconnected. want to reconnect?"

## Costs

- Bootstrap: ~$0.10–$1 per user, dominated by stages 1–2 LLM passes.
  Sonnet 4.6 input tokens per pass: ~10–30k. Four passes + synthesis:
  ~50–150k tokens. At Sonnet rates: $0.15–$0.45 input + small output.
- Live: ~free per message. Webhook handler is non-LLM. Body storage
  cost is Postgres bytes only.
- Composio: per-action pricing per their plan. Not modeled here.
- Daily reconcile: negligible (header pulls, diff, no LLM).

Per-turn cost discipline (CLAUDE.md) is unaffected — the brain loop
never calls Composio synchronously.

## Risks

- **Composio API drift.** Names of triggers and SDK methods may shift.
  Mitigation: thin wrapper module (`backend/integrations/composio.py`)
  that all callers go through; vendor names are localized to one file.

- **Webhook delivery loss.** Mitigated by daily reconcile.

- **Body storage privacy.** Bodies for full-depth messages sit in
  Postgres. v1 stores plaintext; encrypt-at-rest or KMS-wrap is a
  follow-up. Document: "if you store secrets in Gmail bodies, Donna's
  database holds them in plaintext today."

- **Biography drift.** Bootstrap is one-shot. After 6 months, the
  biography may be stale. Mitigation deferred: a periodic re-bootstrap
  task (e.g. monthly), or incremental updates from live ingest. Out of
  v1 scope; documented as a follow-up.

- **GDPR / right-to-delete.** Disconnect must be user-initiated and
  cascade. v1 supports manual disconnect via Composio; data purge tool
  is a follow-up. Documented.

- **Tool-count creep.** v1 adds 3 hand-written tools (`connect_integration`,
  `list_gmail_recent`, `read_gmail_thread`) on top of existing surface.
  Within budget but tracked.

## Test plan

**Unit:**
- `classify_depth` policy — table tests over label combinations.
- Webhook signature verification — accept/reject vector.
- Bootstrap stage selectors — date windows, label filters.
- Biography patch shape — schema validation, idempotent merge.

**Integration:**
- Mock Composio API — full connect → bootstrap → biography happy path.
- Webhook ingest — gmail.new_message and calendar event changes.
- Reconcile — synthetic gap; verify fill.

**Manual (dev environment):**
- Real Google account; full connect; verify biography written; verify
  `[INTEGRATIONS]` block; verify list_gmail_recent + read_gmail_thread.

**Cost smoke:**
- One real bootstrap on a real account, log token usage; verify under $1.

## Implementation phases

**P1 — Schema + auth round-trip**
- Add `integrations` table migration.
- `connect_integration` tool.
- Webhook endpoint with `connection.complete` only.
- `[INTEGRATIONS]` context block.
- *Done when*: user can run `connect_integration`, tap link, and see
  `connected` in their next turn's context. No data sync yet.

**P2 — Live ingest**
- Add `email_messages` table migration.
- Subscribe gmail + calendar triggers on connection complete.
- Webhook handlers for `gmail.new_message` and calendar event changes.
- Label-router function.
- `list_gmail_recent`, `read_gmail_thread` tools.
- *Done when*: new emails arriving in real Gmail land in
  `email_messages` within seconds; calendar events round-trip
  similarly.

**P3 — Bootstrap pipeline**
- Stages 1 + 2 + 3 as background jobs.
- Biography synthesis pass.
- Renderer extension for `BIOGRAPHY` block.
- *Done when*: a fresh connect produces a non-empty
  `living_profile.biography` and the rendered block appears in the
  system prompt for the next turn.

**P4 — Reconcile + hardening**
- Daily reconcile cron.
- Disconnect detection + state surfacing.
- *Done when*: a synthetic missed-webhook scenario gets caught up by
  reconcile within 24h.

Each phase ships independently and is observable through Donna's
existing instrumentation (`donna_runtime/observability.py`).

## Open questions (resolve at impl time)

- Exact Composio trigger names for gmail-new-message and calendar
  events (verify against current Composio docs).
- Whether to store the `email_sender_aggregates` permanently or
  recompute at biography time. Lean: recompute (cheaper, fresher).
- Whether the connect tool should emit one URL or per-product URLs.
  Lean: one URL covering both products in a single Google OAuth
  consent screen, since the products share the same Google account.
- Authentication of the webhook endpoint when Composio's IP / signature
  scheme is verified at impl time.
