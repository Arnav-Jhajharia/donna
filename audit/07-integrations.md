# 07 — Integrations

Headline question: **can Donna proactively suggest things from Gmail / Drive / Calendar today?**

Short answer: **partly Gmail. A little Calendar. Not Drive. Nothing cross-source.** The plumbing is real, the smartness is mostly summarisation, and Drive is connected for the OAuth scope but unused.

## 1. What integrations exist

Everything goes through Composio. There is no direct Google client.

**Gmail** — fully wired.
- Read tools: `list_gmail_recent`, `read_gmail_thread` (typed Donna tools, fast, hit the local mirror in `email_messages`).
- Action tools: none typed. To send mail, the model has to fall back to the generic `composio_execute_tool` and remember the slug (`GMAIL_SEND_EMAIL`). There is no first-class `send_email` tool.
- Webhook: `GMAIL_NEW_GMAIL_MESSAGE` trigger fires `gmail.new_message` → `ingest_gmail_message` → `maybe_surface_email`.

**Calendar** — read + ingest.
- Read tools: `list_calendar`, plus `check_calendar` for availability (per `tools.py`).
- Action tools: no typed `create_event`. Same story — passthrough via `composio_execute_tool`.
- Webhooks: created / updated / deleted events all flow through `ingest_calendar_event` → spawner.

**Drive** — connected but inert.
- OAuth path: `connect_integration(toolkits=["googledrive"])` works, watcher marks it connected, notify pings the user.
- Tools exposed to brain: **zero**. No `read_drive_doc`, no `search_drive`, no Drive ingest pipeline. Grepped the runtime — nothing. The only way to read a Drive file is the model guessing a `GOOGLEDRIVE_*` slug and calling `composio_execute_tool`.
- No webhook subscriptions for Drive changes.

**Slack / Notion / Linear / GitHub / Asana / Hubspot / Salesforce / Intercom** — connectable.
- `connect_integration` accepts any Composio slug, and `notify.py` has friendly labels for them. But there are no typed read or action tools, no webhook subscriptions, no ingest. They are just OAuth + a row in the integrations table. The brain has to drive everything via `composio_execute_tool`. Connecting Slack does not even fire bootstrap (`_BOOTSTRAP_TOOLKITS` in `oauth_watcher.py` is gmail/calendar/drive only).

## 2. The Composio layer

Flow when a user says "connect google":

1. Brain calls `connect_integration(toolkits=["gmail","googlecalendar","googledrive"])` (`backend/memory/tools/connect_integration.py`).
2. `composio_meta.resolve_auth_configs` looks up auth-config IDs per toolkit, falling back to `manage_connections` to auto-provision (this is where managed toolkits like googledrive get created on first use).
3. `composio_meta.initiate_oauth_chain` builds a redirect chain — each toolkit's `callback_url` points to the next toolkit's `redirect_url`, so one tap walks all three OAuth flows.
4. State is mirrored into the `integrations` table as `pending`, with the chain head URL cached for 4 minutes (re-asks reuse it).
5. User taps. Composio fires `composio.connected_account.created` per toolkit to `/webhooks/composio` (HMAC-verified against `COMPOSIO_WEBHOOK_SECRET`).
6. Webhook handler marks connected, calls `client.subscribe_triggers` to register the live triggers, fires immediate-confirm WhatsApp ping, and kicks off `run_bootstrap_async`.
7. Belt-and-braces: `oauth_watcher` polls Composio for ACTIVE status from a PostToolUse hook in case the webhook never lands. Same downstream effect.

Two paths converge on the same outcome — connection mirrored, triggers subscribed, bootstrap fired, user pinged.

## 3. Bootstrap on connect

When **gmail** lands (and only then — `_BOOTSTRAP_TOOLKITS` is gmail/calendar/drive but the bootstrap algorithm itself is gmail-driven), `run_bootstrap_async` runs three stages plus biography:

- `bootstrap_today_dense` — every message from the last ~24h, full bodies, classified, ingested.
- `bootstrap_30d_important` — `is:important newer_than:30d`, capped at 300, full bodies.
- `bootstrap_calendar` — analogous calendar backfill.
- `bootstrap_90d_aggregates` — metadata-only scan of last 90 days, top-50 senders + sample subjects. Capped at 200 messages so bootstrap stays under ~50s.
- `synthesize_biography` — four LLM passes (relationships / work / interests / life signals) plus a synthesis pass. Output written to `users.living_profile.biography`. This is what the importance scorer keys off later.

Idempotent (1h dedupe window so multi-toolkit OAuth doesn't trigger three concurrent bootstraps), persists status to `living_profile.bootstrap_runs`, and notifies the user when done with stage=`bootstrapped` ("alright. read through your inbox, got a sense of who matters.").

Drive is not part of bootstrap. Connecting drive triggers the gmail bootstrap (because it's google) but no Drive content is ever pulled.

## 4. Ingest cadence

**Gmail / Calendar:** event-driven. Webhook on every new message / event change. There is no polling catch-up sweep — if Composio drops a webhook, that message is gone from Donna's mirror unless the user later asks something that forces a `list_gmail_recent` call.

**Calendar spawner sweep:** `spawner_worker.run_forever` runs once per 24h (`SWEEP_INTERVAL_SEC = 86400`), re-evaluates events firing in the next 24h per active user, with the dedup ledger preventing repeats. This is for spawning *attentions*, not for re-ingesting events.

**Drive:** no cadence. Period.

## 5. Smartness — does Donna proactively suggest from integration data?

This is where it falls short of the vision.

**Gmail (`proactive_email_trigger.py`):**
- Score is purely deterministic (`email_importance.py`): IMPORTANT label → +0.5, STARRED → +0.5, sender matches a `biography.relationships` row → +0.0–0.6 by frequency, open-loop keyword in subject/body → +0.5, recent-sent-thread → +0.2. Threshold 0.5.
- If above threshold, the proactive dispatcher runs: Tier 2 judge decides ship / hold / drop, rate limits enforce 3/day + 30min cooldown + topic dedup + quiet hours.
- What actually fires: Donna pings "hey, [thing happened in this email]." It is real surfacing, not just summary on demand. But the *suggestion* is "look at this" — not "this email proposes Thursday at 3pm, want me to add it to your calendar?" There is no action proposal layer. Tier 2 escalates to a brain turn which can pick any tool, but there's no scaffold that nudges it toward "create a calendar event from this email."

**Calendar spawner (`proactive/spawners/calendar.py`):**
- Real but narrow. Title-keyword match against `templates.json` → `exam`, `flight`, `medical` get high-confidence wake-ups + prep reminders. Long meetings with ≥2 attendees get classified `stakes_meeting` → 15min prep ping. Routine standups/syncs are dropped to the existing `CalendarRecurrenceProposer`. Social events (lunch, drinks) are dropped.
- This is genuinely proactive: the spawner *creates an attention* that the schedule_worker fires at the right time.
- Limit: prep reminders are generic ("prep me 15 minutes before {title}"). They don't pull threads, find the deck, or summarise context. The `one_on_one_biography` template hints at "quick read on recent threads" but it just routes through the regular brain turn — no special prefetch.

**Drive proactive:** none. There is no "you saved a doc last week, want me to surface it?" There are no Drive triggers wired in `_PRODUCT_TRIGGERS`. There is no Drive content in any mirror table.

**Cross-source ("email mentions Thursday 3pm meeting, calendar is empty then — want me to add it?"):**
- Does not exist. The email scorer does not look at `CalendarEntry`. The calendar spawner does not look at email or Drive. The biography synthesis reads gmail only. The judge sees the email envelope plus open-loop keywords, nothing else.
- The closest thing is the open-loop keyword bump in `email_importance.py` — if the email mentions text that matches an existing open loop, it scores higher. That's it.

**The `notify` helper:** purely lifecycle pings ("gmail's in", "alright, read through your inbox"). Two stages, dedupe, friendly copy. It is *not* a proactive-suggestion channel — the brain dispatcher owns those.

## 6. Production state

- `composio_api_key` and `composio_webhook_secret` are read from settings (`config.py:41-42`). Webhook routes accept both `/webhook/composio` and `/webhooks/composio` because user accounts have both configurations live. Signature verification is HMAC-SHA256, constant-time.
- `COMPOSIO_GOOGLE_AUTH_CONFIG_ID` (the env var the user mentioned, value `ac_jOyH88uMqRwc`) is **not referenced anywhere in code** — grep finds zero hits. The system instead uses `composio_meta.resolve_auth_configs` to query Composio for the auth config per toolkit, with `manage_connections` as auto-provision fallback. So the env var is either legacy or dashboard-only metadata. The resolver pattern works without it.
- The dual webhook + watcher belt-and-braces design plus the 1h bootstrap dedupe suggests this is shipping in prod and has been hardened against real-world race conditions (multi-toolkit OAuth, dropped webhooks, duplicate connection.complete events).
- Whether real users are connected today: code paths exist for it (idempotency, reconcile-on-connect, redirect cache), and there are stale `bootstrap_runs` migration entries — strongly implies yes, at least some.

## 7. Gaps + opinion

The plumbing is solid. Gmail is ingested, biography is synthesised, the importance scorer and dispatcher fire real proactive pings under quota. Calendar gets prep reminders for high-stakes events.

But the user's example — "email says let's meet Thursday at 3pm, deck deadline is Thursday, connect those dots" — does not happen today. There is no cross-source reasoner. The email scorer sees the email in isolation. The calendar spawner sees calendar events in isolation. Biography reads gmail only. Drive isn't read at all.

**Smallest change that closes the headline gap:** when an email scores above threshold, before invoking the brain, fetch (a) the user's calendar window for whatever date the email mentions and (b) any open loops whose keywords match. Pass both into the trigger prompt. The brain already has the tool surface (`list_calendar`, `list_open_loops`) so the *capability* exists — the gap is that the proactive prompt doesn't pre-load that context, and Tier 2 judge gets only the email envelope. Adding a "prep_context" block to the email proactive event would let the judge / brain say "this email mentions Thursday 3pm, calendar is open, want me to add it?" without needing new tools, new ingest, or a Drive integration.

Drive's gap is bigger and harder: it's connected for OAuth scope but has zero ingest. To make Donna notice "you haven't opened the doc you saved last week" needs a Drive ingest mirror, change-notification subscription, and a freshness signal — none of which exist. It's a green-field add, not a tweak.

## Verdict

- **Architecture:** Strong. The Composio abstraction is clean, the redirect-chain trick is genuinely good UX, the dual webhook+watcher pattern is defensible, the bootstrap → biography pipeline is the right shape.
- **Production:** Live. Gmail and Calendar are wired end-to-end with hardening that only ships from real incident response. Drive is connected but inert.
- **Gap to vision:** Significant. Donna can surface that an important email arrived. She cannot connect an email to a calendar gap, or a calendar event to a Drive doc, or notice that Thursday is filling up. She is "passive plumbing with smart Gmail surfacing on top" — not yet a thinking partner who notices things across surfaces. The gap is not capability, it's wiring the capabilities together. Closest one-week win: cross-source context in the proactive email prompt.
