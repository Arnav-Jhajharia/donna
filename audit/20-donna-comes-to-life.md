# 20 · Donna Comes To Life — the unified audit

The other 18 audits are honest about gaps in *subsystems*. This one is about whether Donna, as a *single coherent product*, is alive.

The pitch: Donna holds your life, attends to what's becoming important, reaches out before things slip, and renders the editorial view of your day on a paper-toned dashboard. She is a presence, not an assistant.

Reality on 2026-05-01: most of the plumbing is built. The choreography isn't. Most archetypes are unreachable. Most action verbs are stubs. Most "Donna initiates" loops don't fire. Mirror mode means cooldown rows aren't written. The brain is told to be high-agency but trained — by repeated examples — to ask permission. The dashboard is a museum of design intent, not a tool she actively uses. **She is mostly a chatbot with two readers (Gmail, Calendar) and a beautiful design system she can't reach.**

This document covers:
1. **What "Donna comes to life" looks like** — the perfect day, hour by hour, anchored on archetypes + tools + WhatsApp choreography
2. **The Attention game, re-grounded** — the canonical structure all "things she noticed" must flow through
3. **The truth about what fires today** — every loop, what wakes it, whether it's actually running
4. **The clunkiness audit** — specific architectural friction, file + line cited
5. **The behavior-quality audit** — what the brain does wrong despite the prompt being right
6. **The dashboard reachability audit** — 17 of 18 archetypes orphaned; 13 of 16 action verbs return 501
7. **The integration sense gap** — Donna sees too little to be Donna
8. **The unified plan to make her feel magical** — what ships first, what ships next, the sequencing
9. **The smallest first move** — the proof point that costs ~3 days

Test status (run during audit): `pytest donna/attention/tests/` → 238 passed. `pytest backend/tests/` → 1 failed (`test_exam_event_spawns_two_live_attentions` in [backend/tests/proactive/test_spawner_calendar.py](../backend/tests/proactive/test_spawner_calendar.py)), 275 passed. The failing test is a real regression in calendar spawner attention materialisation — flagged below.

---

## Part I · What "Donna comes to life" looks like

### The canonical product moment (the one nobody else has)

> 5:42pm. Arnav's WhatsApp lights up:
> "you're not avoiding him. you're avoiding the conversation. 9 days. tomorrow's clear after 4."
> He taps the line. Dashboard opens cold-loaded: a single oxblood-bordered c-confront block with the same words. Below it, a c-reflection: "what would happen if you said it badly?". Below that, footer: "i'll hold this. you don't have to answer now."
> No tracker grid. No news brief. No watches. The day got compressed because the moment was heavy.
> Two minutes later he texts back "fuck. ok i'll call him after the dentist."
> She replies: "set. wednesday 6pm reminder, won't ping again unless you ask."
> The dashboard recomposes silently. The c-confront is gone. A small c-reminder appears in its place. Footer changes: "see you wednesday."

Three things make this moment Donna and not a chatbot:
1. **She noticed without being asked.** The 9-day silence + open loop drift came from the noticer reading the mirror, not the user typing.
2. **The chat and the dashboard say the same thing at the same moment.** The WhatsApp burst and the recomposed manifest are two surfaces of one editorial decision.
3. **She compressed.** The 18-archetype catalogue includes 5 things Arnav usually sees in the morning. Tonight the dashboard has 1 thing. The composer chose silence on the rest because the moment didn't earn them.

None of this works today. Each of the three things is broken at a specific code line.

### The perfect day — hour by hour, what she should do, what she actually does

Setup: Arnav (UTC+5:30, India). Gmail + Calendar connected. Drive scope granted but inert. Wakes ~7:30. First engage typically 8:00. Pitch day; principal call at 14:00; deck due to Maya by Friday (it's Wednesday); 9-day silence with his dad.

| Time | What she should do | What today's code does | Gap (file·line) |
|---|---|---|---|
| **02:00 IST** | Synthesis worker rebuilds Living Profile. Reads chat + observations + open loops + calendar + Gmail mirror. Writes `narrative`, `today_shape`, `watch_for_tomorrow`. **Plus**: re-reads `email_messages` mirror for stale-commitment signal ("deck → Maya by Friday, 2 days left, no draft sent"); re-reads `drive_documents` for stale-doc signal ("deck modified Sunday, 3 days untouched"); writes those as observations or shadow Attentions for morning. | Synthesis worker fires. Reads gmail + calendar + chat + observations. Writes LP fields. **Doesn't read drive (no mirror). Doesn't read email_messages for commitment-drift (no proposer). Doesn't write shadow Attentions from synthesis** — synthesis only writes Living Profile fields. | [backend/memory/jobs/synthesis_worker.py](../backend/memory/jobs/synthesis_worker.py) — synthesis ↔ attention systems are siblings, not connected |
| **05:00 IST** | Morning digest refresh: `yesterday`, `today_shape`, narrative reread. Dashboard recomposes preemptively so when Arnav wakes, the manifest is fresh. | Morning digest fires. Living Profile fields refreshed. **Dashboard does NOT recompose** — composer is only invoked on accept_attention or first GET. | [backend/web/proactive/triggers/morning.py](../backend/web/proactive/triggers/morning.py) — never calls `compose_manifest` |
| **07:42** | Arnav opens phone. Donna stays silent (cold-start protection: he hasn't engaged yet, typical_first_engage_window starts 8:00). | Same. Silent until 8:00 ± 30min window. | OK |
| **08:05** | Inside engage window. `watch_for_tomorrow` is non-empty ("principal call at 2 — eat first; deck still drifting; dad — 9 days"). Morning trigger fires WhatsApp burst: "principal call at 2. eat first. deck for maya is still where it was sunday — drafting it today?" **Dashboard recomposes simultaneously**: hero greeting + c-prep (principal call: 4-item checklist) + c-tracker (hydration, 1 of 8 glasses) + c-confront (quiet variant): "9 days without calling him." Footer. | Morning trigger fires WhatsApp burst (this works as of `donna-synthesis` Railway service launch). **Dashboard does not recompose**. **No commitment-drift signal** (deck never makes it into prompt; no proposer reads email_messages). **No 9-days-silence signal** (no proposer for relationship dormancy). The burst is generic morning copy unless `watch_for_tomorrow` happens to surface it. | [morning.py:269](../backend/web/proactive/triggers/morning.py#L269) ships text but not dashboard recompose; [donna/attention/propose.py](../donna/attention/propose.py) has 5 proposers, none for commitment-drift or quiet-relationship |
| **08:30** | Arnav reads briefing in chat. Taps dashboard link from morning burst. Dashboard hero says exactly what the chat said. **Same editorial line, two surfaces.** He taps c-prep "draft the deck" — this fires action verb `start_tracker` or `accept_attention`, the deck thread surfaces in chat: "drafted opening 3 slides — your thesis from Sunday's voice note. want it in the deck or rewritten?" | Arnav reads briefing. Taps dashboard link. **Dashboard is empty** (no manifest exists, or stale manifest from yesterday). Sees "your dashboard is being composed" — a 404 false-promise message that doesn't actually compose. He texts back "redo my dashboard" → composer runs → 30-second wait → dashboard appears, but disconnected from the morning thesis. | Audit 17: empty 404 dead loop ([dashboard/web/app/page.tsx:178](../dashboard/web/app/page.tsx#L178)). No magic-link mint hook ensuring dashboard is fresh on first tap. Action verbs return 501 ([api/dashboard_routes.py:194](../api/dashboard_routes.py#L194)) for 13 of 16 verbs |
| **09:23** | Maya emails: "still good for thursday 3pm? need the deck by then." Email scorer + cross-source resolver: this email is a **meeting_request + deadline_reference** intent. Arbiter checks: not in quiet hours, not active chat, allowed. **Tier 2 judge gets enriched payload**: email + drive_documents (deck status: 3 days untouched) + calendar (thursday 3pm: open) + open_loops (deck → maya by Friday). Judge drafts: "maya wants the deck by thursday 3pm. you have a 1h window before the principal call. drafting now or this evening?" **Dashboard recomposes silently**: c-prep card updates from "principal call" to "principal call + deck-by-thursday" with both checklists merged. | Email arrives. Scorer fires (deterministic, isolation-only). Score > 0.5 because "open loop keyword match" (deck/maya). Arbiter passes. **Tier 2 judge runs in mirror mode** ([proactive/dispatcher.py](../proactive/dispatcher.py)) — logs decision, **doesn't ship, doesn't write ProactivePing**. Legacy brain path runs in parallel — Sonnet generates a reactive turn that surfaces this generically because **Tier 2 prep_context doesn't include calendar / drive / open_loops cross-source data**. Donna says: "maya wants the deck by thursday." That's it. The cross-source connection is invisible. | Audit 04: mirror mode + cooldown table empty. Audit 07: cross-source reasoner doesn't exist. Audit 08: research/recall don't fanout calendar/drive/email together. The email proactive trigger is a parallel path to Attention (the user's own opinion: that's wrong) |
| **11:00** | Mid-morning quiet check. Donna has the `typical_message_gap_median_hours` rhythm field. Arnav usually messages every 90 min when active; it's been 2.5 hours since 08:30. **Mid-morning proposer**: "is the day still on track? deck is at 3 of 8 slides per drive_documents.last_modified — going OK?" Single soft burst. No dashboard recompose unless he replies. | **Nothing fires.** No mid-morning trigger exists. Synthesis worker polls every 5min but only fires morning at 05:00 anchor. No "Donna initiates" loop covers the 11am window. | Audit 04: "no random trigger beyond morning." There is no `MidMorningTrigger`, `MiddayTrigger`, `EveningTrigger`, or `LateTrigger`. |
| **13:30** | Pre-meeting prep ping (30 min before 14:00 principal call). Calendar spawner fired this attention at calendar-event-creation time. It's now LIVE; schedule_worker fires it. WhatsApp burst: "principal call in 30. one-line read: she's the partner from sequoia — cared about retention numbers in the seed memo. you have those." **Dashboard recomposes**: the c-prep card moves to c-watch (active during meeting), with the partner profile pulled from biography, retention metric pulled from drive_documents (the seed memo). | Calendar spawner *exists* and *would* fire if `DONNA_SPAWNERS=1`. **It is unset in prod**. Even if set, the prep_doc card has no body content because Drive is inert — biography only synthesizes from gmail. The reminder text would be generic "principal call in 30." | Audit 04: `DONNA_SPAWNERS=1` unset. Audit 07: Drive inert, biography is gmail-only |
| **14:00** | Meeting starts. Donna goes silent (active-chat detection extends to "user is in a meeting" via calendar.now()). Arbiter raises a "active_meeting" gate. No proactive ships during 14:00–15:00. | Active-meeting suppression doesn't exist in arbiter. If an email arrives at 14:30, the same scoring + judge fire — could ping mid-meeting. | [backend/integrations/proactive_rate_limit.py](../backend/integrations/proactive_rate_limit.py) — no `is_in_meeting` gate |
| **15:15** | Meeting ends. Calendar event has `end_time`. **Post-meeting trigger** fires (15-min delay): "how'd it go? want me dropping a hot note while it's fresh?" If Arnav replies with content, log_observation captures the read. If not, the prompt evaporates. | **No post-meeting trigger exists.** Calendar spawner fires *before* events; nothing fires *after*. | Calendar spawner is one-direction (prep only) [proactive/spawners/calendar.py](../proactive/spawners/calendar.py) |
| **16:00** | Quiet afternoon. The dashboard has been showing prep + tracker since morning. Now it shifts: c-prep collapses (meeting done), c-tracker remains (3 of 8 glasses, slow day), c-watch appears with the deck status ("3 of 8 slides → 4 of 8" if Arnav opened drive in the last hour). | Dashboard hasn't recomposed since morning's empty-404 manual prompt (if it composed at all). Whatever's there is stale. | No state-driven recompose loop |
| **17:42** | The 9-days-without-calling-dad signal hits a soft confrontation threshold. **Confrontation proposer** (doesn't exist) reads relationship dormancy from biography + chat history. Materialises a c-confront archetype with quiet variant. WhatsApp burst: "you're not avoiding him. you're avoiding the conversation." Dashboard recomposes to the moment described in the opening canonical scene. | **No confrontation proposer.** Closest existing thing: `EntityMentionProposer` ([propose.py:379](../donna/attention/propose.py#L379)) detects entity repetition but only for general-purpose mentions, not relationship dormancy. No `c-confront` block emitted by composer because **prompt doesn't teach c-confront**. | [propose.py](../donna/attention/propose.py) missing proposer; [compose.py:144-158](../backend/dashboard/compose.py#L144) doesn't reference c-* archetypes |
| **20:00** | Evening recap. Counterpart of morning trigger. Reads what landed today: deck went to 5/8 slides, hydration at 4/8 (low), principal call done, dad still pending, one open commitment (maya thursday). One-line read: "deck moved to 5 of 8. principal landed. dad — wednesday after dentist." Dashboard moves to night register: c-openloop list (3 items) + c-reflection ("one thing you'd carry tomorrow?") + footer "see you in the morning." | **No evening trigger.** Synthesis worker only fires morning + nightly full sync. | Audit 06: "no evening briefing counterpart exists" |
| **22:30** | Arnav is winding down. Donna stays silent unless he writes. If he does ("can't sleep"), reactive turn reads LP for emotional_temperature, voice softens, no dashboard recompose unless he asks. | This works (reactive turns work fine). | OK |
| **00:30** | Quiet hours kick in (00:00–07:00 default if no sleep_time fact set). No proactive fires. Reminders queue continues to drain. | Works. | OK |

**The shape of the gap is clear:** today Donna fires at most 3 proactive moments per day (morning briefing, email proactive, calendar prep). The day above has ~10 proactive moments, half of which require infrastructure that doesn't exist. **The other half exist as code but don't run** (proposers shadow but don't promote in prod; calendar prep gated off by `DONNA_SPAWNERS=1` unset; mirror mode means email proactive doesn't actually ship).

---

## Part II · The Attention game, re-grounded

The user's framing in this conversation: "Attention is simply our way of making a structure out of things Donna notices or the user wants Donna to notice. It may not be a perfect structure but it's what we have. Ideally, integrations should flow through that."

This is right and changes the architecture.

### The single principle

**Every "Donna noticed X" emits an Attention.** Lifecycle, urgency, and surfacing rules vary by `kind`, but the noun is the same. One pipeline, one dispatcher, one place the dashboard reads from.

```
    chat phrase                ─┐
    observation frequency      ─┤
    deadline approaching       ─┤
    calendar recurrence        ─┤
    entity mention             ─┤
    email arrival              ─┤   PROPOSERS
    drive doc shared           ─┤   (read input
    drive doc stale            ─┤    sources)
    slack DM landed            ─┤
    commitment drift           ─┤
    relationship dormancy      ─┤
    inbox spike                ─┤
    user explicit ("watch X")  ─┘
                                 │
                                 ▼
                    AttentionDraft (kind, subject, payload)
                                 │
                                 ▼
                            shadow ─── promoter ticks (counts hits)
                                 │
                          ┌──────┴───────┐
                          │              │
                       offered     quietly_archived
                          │
                  ┌───────┴───────┐
                  │               │
                 ship          rejected
                  │
              live attention ──── fires on cadence ──── donna_schedule
                  │                                          │
              dispatcher                                schedule_worker
              ↓ (judge, voice_validator)                     ↓
          WhatsApp burst                                WhatsApp burst
          + dashboard recompose                         + dashboard recompose
```

### The 6 cards already cover everything

The `donna/attention/README.md` lists 6: `event_stream | tally | brief | prep_doc | open_loop | ping`. Mirror-derived signals fit:

| Signal | Card | Variant on dashboard |
|---|---|---|
| Maya shared a doc with you | `event_stream`, `subject="Maya"`, source=drive | c-watch (rows variant) |
| Hydration tracking proposal | `tally`, `subject="hydration"` | c-tracker (pair) → if accepted, c-tracker (hero) |
| Inbox is spiking | `tally`, `subject="inbox_volume"`, surface_rule=ambient_only | not rendered; feeds prompt's `coverage` |
| Aarav silent 14d | `tally`, `subject="aarav"`, kind=relationship_dormancy | c-person (hero) |
| Deck → Maya by Friday, drifting | `open_loop`, deadline-aware | c-openloop (quote variant, overdue flag) |
| Friday morning brief on launch | `brief` | c-brief (newsstand) |
| Principal call prep | `prep_doc` | c-prep (inline checklist) |
| 14:00 hydration reminder | `ping` | c-reminder (pill) |
| Evening confrontation about dad | `open_loop` w/ kind=relationship_drift OR new card `confront` | c-confront (quiet) |

The new addition would be a **`confront` card** for hard-truth attentions (audit 17 evening scene). Could also fit under `event_stream` with a confrontation flavor, but a dedicated card makes the dashboard composer's job clean.

### The Attention surfacing has 3 modalities, not 1

This is the part the existing code doesn't yet model:

1. **Push** — Donna texts the user about it. WhatsApp burst, possibly dashboard recompose. Lifecycle: `live` attentions firing on cadence; `offered` attentions when active-push is gated on (`DONNA_PROACTIVE_OFFER_ACTIVE=1`).

2. **Pull** — On the dashboard when the user opens it. Composer reads OFFERED + LIVE pools, picks 2-4 that earn screen-space tonight, compresses or hides the rest. **No WhatsApp burst.**

3. **Ambient** — Feeds the prompt's `coverage` block; never surfaces directly. Used for tone modulation ("inbox is spiking → soften"), state awareness ("she's been quiet 4 hours"). The Attention exists in `shadow` permanently; it's read but never offered or promoted.

The existing schema (per [db/models.py:489](../db/models.py#L489)) supports modality 1 and 2. Modality 3 needs a new `surface_rule: ambient | offered | push` column or a `kind` enum value.

### The integration → attention bridge

For each integration:

- **Mirror** keeps a per-user copy of the data. (Slice 0 from earlier conversation: `mirror_cursors` table + `MirrorSync` base class.)
- **Mirror-aware proposers** in [donna/attention/propose.py](../donna/attention/propose.py) read mirrors and emit candidate Attentions in `shadow`. New proposers: `DriveShareProposer`, `DriveStaleDocProposer`, `CommitmentDriftProposer`, `QuietRelationshipProposer`, `InboxRhythmProposer`, etc.
- **The existing promoter, dispatcher, judge, voice-validator, schedule_worker do not change.** They consume Attentions; they don't care where they came from.

The `proactive_email_trigger.py` ProactiveEvent path is **legacy alongside**. New integrations follow the Attention pattern. Email proactive can migrate later.

---

## Part III · The truth about what fires today

Loops actually wired in code (from the loops audit + my reading):

| Loop | Cadence | Where it runs | **Actually fires?** |
|---|---|---|---|
| Schedule worker (DonnaSchedule fires) | Poll 5s, batch 25 | `donna-reminders` Railway | ✅ Yes (deployed 2026-04-28) |
| Synthesis worker (LP rebuild) | Poll 5min; nightly 02:00 local; morning 05:00 local | `donna-synthesis` Railway | ✅ Yes |
| Morning proactive trigger | Anchored at 05:00 local, gated by typical_first_engage_window | Inside synthesis worker tick | ✅ Yes (when LP has watch_for_tomorrow) |
| Attention propose pass | Every 30 min | `donna-attention` Railway | 🟡 Yes, but proposers create shadow, **promoter rarely promotes** |
| Attention promote pass | Every 15 min | `donna-attention` Railway | 🟡 Yes, but `DONNA_PROACTIVE_OFFER_ACTIVE=1` unset → OFFERED never actively pushes |
| Spawner sweep (calendar 24h ahead) | Daily, polled every 60s | API only if `DONNA_SPAWNERS=1` | ❌ Flag unset in prod |
| Brief refresh (temporal brief) | Every 2h | API only if `DONNA_BRIEF_REFRESH=1` | ❌ Flag unset in prod |
| WhatsApp inbound → brain | Event (webhook) | API | ✅ |
| Gmail webhook → ingest → score → dispatcher | Event | API | 🟡 Mirror mode only — Tier 2 judges, doesn't ship; legacy brain path runs in parallel |
| Calendar webhook → ingest → spawner | Event | API | 🟡 Spawner runs but materialises **shadow** Attentions; without active-push, user never sees them |
| Composio account.created → bootstrap | Event | API | ✅ Gmail bootstrap fires, biography synthesizes |
| `run_proactive_tick` (active world engine) | Should be cron | `backend/web/proactive/runner.py` | ❌ **Dead code** — never invoked in prod (audit 19) |
| Mid-morning / midday / evening / late triggers | Should fire on cadence anchors | Don't exist | ❌ Not built |
| Drive ingest | Should be webhook + cursor sync | Don't exist | ❌ Drive inert (audit 07) |
| Slack/Notion/Linear/GitHub ingest | Should be sync | Don't exist | ❌ Not built |
| Mirror-aware proposers (commitment-drift, quiet-relationship, drive-share, inbox-rhythm) | Should run on attention propose pass | Don't exist | ❌ Not built |
| Post-meeting trigger | Should fire 15min after calendar event end | Doesn't exist | ❌ |
| In-meeting suppression | Should gate arbiter | Doesn't exist | ❌ |

**The honest summary:** today, on a typical user-day, Donna fires 1-3 proactive moments (morning briefing if LP has a watch; email proactive if mirror flag flips; calendar prep if `DONNA_SPAWNERS=1` flag flips). The "presence" promise rests on these fires landing well. The rest of her promised behaviors are either gated off, not yet implemented, or implemented but disconnected from the surfacing pipeline.

### The failing test (caught during this audit)

`pytest backend/tests/proactive/test_spawner_calendar.py::test_exam_event_spawns_two_live_attentions` fails. The calendar spawner is supposed to materialise multiple Attentions for compound calendar events (e.g., "exam tomorrow 11am" → wake reminder + 1-hour-before reminder). The test expects two LIVE attentions; the spawner produces something else. **This is a real regression** — calendar spawner is one of the few proactive paths that's actually wired, and a piece of it is broken right now. Worth fixing immediately.

---

## Part IV · The clunkiness audit (specific architectural friction)

The user said "code seems clunky af to me right now." Yes. Specifically:

### IV.1 · Two parallel paths for "Donna noticed something"
[proactive/dispatcher.py](../proactive/dispatcher.py) consumes `ProactiveEvent` directly from `proactive_email_trigger.py`. Same dispatcher *also* consumes Attention promotions via `attention_offer.py`. **Same downstream pipeline, two upstream entry shapes.** The judge prompt has to be source-agnostic; the arbiter's cooldown table has to track both; the dispatcher branches on event source. This is the single biggest clunk in the proactive layer. The user's correction in this conversation was right: Attention is the canonical structure. Email should emit Attentions, not ProactiveEvents.

**Fix:** delete `proactive/sources/email.py` adapter; refactor `proactive_email_trigger.py` to call a new `EmailArrivalProposer` that materialises an Attention with `kind=fresh_arrival`, short shelf-life. Dispatcher sees Attentions only. ~3 days work.

### IV.2 · Three signal abstractions where one would do
- **Proposer** (timer-driven, scans data sources) → `donna/attention/propose.py`
- **Spawner** (event-driven, classifies a single event) → `proactive/spawners/calendar.py`, `observation.py`
- **Source** (adapter to dispatcher) → `proactive/sources/`

Same end product (a SHADOW Attention or a ProactiveEvent). Three abstractions to pick between. Adding a new signal type requires guessing which abstraction fits. **This is why integration → attention isn't obvious to wire.** A unified `Signal` protocol with `emit(user_id) → list[AttentionDraft]` would collapse all three.

### IV.3 · Mirror mode without a migration story
`DONNA_PROACTIVE_TIERED=1` flips the dispatcher from mirror (judge runs, doesn't ship, no ProactivePing rows written) to tiered (judge ships). **The cooldown table is empty when you flip.** First flip ships every email because cooldown checks see no history. Audit 04 calls this out. There's no shadow-mode-with-writes (judge runs, ships nothing, **but writes ProactivePing rows so cooldown table populates**). That should exist. ~1 day.

### IV.4 · Two `donna_turn` symbols
[runner.donna_turn](../donna_runtime/runner.py#L32) (legacy CLI helper, saves to `session_store_file` JSON) and [brain.donna_turn](../donna_runtime/brain.py) (production, saves to DB). Same name, different paths. Tests using CLI version don't exercise prod. **Rename one.** ~1 hour.

### IV.5 · `_BOOTSTRAP_TOOLKITS` defined twice
Once in [oauth_watcher.py:37](../backend/integrations/oauth_watcher.py#L37) (frozenset of `gmail/googlecalendar/googledrive`); once implicitly in [api/composio_webhook.py:135](../api/composio_webhook.py#L135) (the slug-routed bootstrap dispatch). Adding Drive ingest means updating both. **Single dispatch table** would cover it. ~2 hours.

### IV.6 · Stage 0 vs Stage 0.5 prompt
[donna_runtime/prompt.py](../donna_runtime/prompt.py) has `STAGE_0_PROMPT` ("you have no memory tools") and `STAGE_0_5_PROMPT` ("memory and action tools available"). Production runs Stage 0.5. Stage 0 is dead. `build_system_prompt` accepts 3 params and `del`s all 3. **Delete the dead branch and the dead params.** ~30 minutes.

### IV.7 · `load_living_profile` is dead code
Self-documented at [prompt.py:15](../donna_runtime/prompt.py#L15): "Kept for compatibility; not used by the current prompt." Production reads via `context_builder.load_user_model_block`. Delete the dead function. ~10 minutes.

### IV.8 · `proactive_max_turns` declared, never read
[donna_runtime/config.py](../donna_runtime/config.py) declares `proactive_max_turns=12`. Grep finds zero readers. Reactive `max_turns=6` is used for both reactive and proactive. Either wire it (if 12 turns is the right ceiling for proactive — it is, per audit 05) or delete. ~1 hour.

### IV.9 · `stay_silent` and `offer` terminators promised in CLAUDE.md, don't exist
CLAUDE.md says terminators are `send_burst | stay_silent | offer`. Grep finds only `send_burst`. **CLAUDE.md is stale or the design was simplified.** Either implement them or trim the doc. The user's MEMORY.md says "trust code over doc" — so delete the doc claim. ~30 minutes.

### IV.10 · `dig_deeper` and `compile_brief` subagents promised, don't exist
CLAUDE.md mentions both as Opus-backed subagents that hide latency for deep research. They're not implemented. `research` runs inline in the brain loop and blocks for 3+ seconds. The Anthropic Agent SDK supports this pattern (sub-tasks via Task tool). **Build them or remove the claim.** ~1 sprint to build properly with a fire-and-forget surfacing pattern.

### IV.11 · `recall_episodic` and `recall_graph` are vestigial
Audit 09 says these are rarely better than `recall(query, purpose=...)`. The brain rarely picks them. They consume tool-catalog tokens. Delete from `DONNA_TOOLS` and remove from prompt. ~20 minutes.

### IV.12 · Five Composio tools where two would do
`connect_integration`, `composio_manage_connections`, `composio_wait_for_connections`, `composio_search_tools`, `composio_execute_tool`. The two-turn flow (manage → wait) is awkward. Three of them overlap on "make a connection." The user-facing tool should be `connect_integration`; the discovery+execute pair is `composio_search_tools` + `composio_execute_tool`. **Drop `composio_manage_connections` and `composio_wait_for_connections`.** Their use cases are subsumed by `connect_integration`. ~half day.

### IV.13 · Schema-vs-prompt drift on `send_burst`
Schema allows 6 items; prompt says max 3. Schema doesn't enforce voice_response position; prompt says first-only. Schema accepts voice + widget combos; prompt says incompatible. **Tighten the schema to match the prompt.** Pydantic `model_validator(mode='after')` catches all three. ~half day.

### IV.14 · The dashboard uses 7 block types in production despite 18 catalogue archetypes existing
[backend/dashboard/compose.py:144-158](../backend/dashboard/compose.py#L144) teaches Sonnet about `thesis | witness | todo-list | reminders | permission | tracker-grid | footer`. Doesn't mention any `c-*` archetype by name. The `/moments` page renders all 18. **The catalogue is design work disconnected from production.** ~3 days to teach the prompt + add type guards in the renderer + write fixture-based prompt evals.

### IV.15 · 13 of 16 action verbs return 501
`accept_attention | dismiss_attention | mark_reminder_done` are wired. The other 13 (`start_tracker`, `complete_pick`, `snooze_reminder`, `connect_integration`, `accept_draft`, `decide_option`, `quick_log`, `open_relationship`, `open_news`, `open_tracker`, `reply_chip`, `log_value`) return 501 ([api/dashboard_routes.py:194](../api/dashboard_routes.py#L194)). Showcase plans render them as if tappable; users tap, get errors, lose trust. **Either wire the 13 or trim the schema down to what's real.** Each verb is ~2-4 hours of work; total ~1 sprint. The honest first move is to trim the schema; you can always grow it later.

### IV.16 · The morning trigger doesn't recompose the dashboard
[backend/web/proactive/triggers/morning.py:269](../backend/web/proactive/triggers/morning.py#L269) ships a WhatsApp burst, never calls `compose_manifest`. **The user reads the burst, taps the link, sees yesterday's manifest.** This is the single highest-leverage UX fix in this whole audit. ~2 hours.

### IV.17 · SSE manifest_changed pubsub is in-process
[backend/dashboard/manifest_events.py](../backend/dashboard/manifest_events.py) — silent no-op across pods. With workers running in their own Railway services (synthesis, attention, reminders), a worker-driven recompose **never reaches** an API-pod SSE client. Dashboard falls back to 20s polling — works, but feels lazy. **Redis pubsub** as the SSE backbone fixes it. ~1 day.

### IV.18 · No active world engine
[backend/web/proactive/runner.py:run_proactive_tick](../backend/web/proactive/runner.py) is fully built — query_creation, executor, judge, gates. Has tests. **Has zero production callers.** The Watch archetype on the dashboard renders dummies because no signal feeds it. ~3 days to wire to a cron + add `user_watchlists` table + 3 source adapters.

### IV.19 · Living Profile orphan fields
`what_changed_this_week` synthesized every cycle, never rendered. `rhythm.typical_quiet_hours` written, never read. Wasted Haiku tokens. Either render them in the prompt or stop generating them. ~30 minutes.

### IV.20 · Calendar spawner test failing
`test_exam_event_spawns_two_live_attentions` fails as of right now. **Real regression in the only proactive path that's actually wired beyond email + morning.** Fix urgently. ~half day to investigate + fix.

---

## Part V · The behavior-quality audit (the brain does the wrong thing despite the prompt being right)

The system prompt (read in full from [donna_runtime/prompt.py](../donna_runtime/prompt.py)) is genuinely good. It's specific, opinionated, voice-coherent. The CAPTURING examples teach the right pattern. SITUATIONAL AWARENESS examples model reactive-with-proactive sharply.

But the brain still misbehaves in predictable ways:

### V.1 · Over-asks on timed events
Despite the prompt's CAPTURING section explicitly saying "you call attend WITHOUT asking," Sonnet sometimes asks "want me to remind you?" The pattern: when the user's phrasing is hedged ("I might have a thing tomorrow at 11"), the brain re-injects the hedge into its move. **Fix:** add a stronger negative example to the CAPTURING section ("DO NOT do this: ..."). ~30 min prompt edit + eval suite.

### V.2 · Over-recalls
The prompt says "do not call recall when LP/SITUATION BRIEF already answers." But the brain doesn't reliably know what's in the LP — it's a 200-char paragraph it has to scan against the user's question. When uncertain, it calls recall to be safe. **Cost discipline drift.** Audit 09's recommendation (cross-backend caching keyed on `(user_id, query_hash)`) helps but doesn't fix the over-call. **Fix:** add to the prompt a "recall skip checklist" — three explicit checks before calling. Plus instrument recall calls with a "was the answer already in LP?" judge for eval. ~1 day.

### V.3 · Under-uses `update_dashboard`
Tool exists at `donna_runtime/tools.py`. Brain rarely calls it on its own. **The prompt mentions it nowhere.** Audit 14 noted this. **Fix:** add prompt clause: "after major state changes (new tracker accepted, big open loop closed, profile materially shifted), consider calling update_dashboard so the user's home page matches what just happened in chat." ~10 min.

### V.4 · Doesn't cross-source on its own
User says "what's happening with Maya?" Brain calls `recall` — which fans out across episodic + graph + observations + brief but **not calendar, not gmail mirror, not drive_documents** (audit 09: 5 of 10 backends). **Fix:** the right structural fix is the 8-lane recall (audit 09). The prompt fix is a single line: "for queries about a person/topic/project, also check calendar (`list_calendar`) and recent mail (`list_gmail_recent`) — they often have context recall doesn't see." ~10 min prompt + ~1 sprint for fanout.

### V.5 · Performs empathy mode-switches but stays at the same depth
When the user is anxious or struggling, the prompt says "acknowledge briefly, then be useful." The brain shifts register correctly but stays surface-level — "rough. anything you want to talk about?" instead of "rough. you have 2h before your call. eat first." The reactive-with-proactive examples in the prompt teach this; the brain doesn't always pattern-match. **Fix:** more eval data with paired (anxious-message, sharp-response) examples to feed the prompt or use as eval. Maybe a "feel like trash → specific move" mini-prompt-tested example added to SITUATIONAL AWARENESS. ~half day.

### V.6 · Forgets `send_dashboard_link` on first message
Prompt says "MUST call before send_burst on first_message=True." If model forgets, no fallback exists. Audit 17 calls this out. **Fix:** PostToolUse hook on `send_burst` checks: if `first_message=True` and no `send_dashboard_link` call in trace, **inject a fallback link before send_burst fires** — or, simpler, append it to the burst text. ~2 hours.

### V.7 · Over-confirms ("done. logged.")
Despite "after private actions" prompt section, the brain sometimes ships explicit "logged ✓" copy. The prompt is right ("don't sound like a receipt"); the brain pattern-matches "user told me a fact → confirm with one word." That's actually fine in moderation but tips into receipt-voice on repetition. **Fix:** voice filter could detect short receipt-shaped replies in burst and route them to the no-emoji clause. Minor. ~1 hour.

### V.8 · Doesn't notice voice-note tone
[donna_runtime/voice_intent.py](../donna_runtime/voice_intent.py) detects when the user **asked for** voice output. It does **not** mark when the user **sent** a voice note. The transcript replaces `raw_input` and the brain reads it as text. The "that voice note was rambling and frustrated" signal is lost. **Fix:** always render `inbound_modality` in the wrapped context (currently optional); add a prompt clause: "if inbound_modality=voice_note, the transcribed text loses tone — read for affect through pace, repetition, hesitation markers." ~1 hour.

---

## Part VI · The dashboard reachability audit

The 18-archetype catalogue (`dashboard/web/components/blocks/catalogue/CatBlocks.tsx` — 62 type/JSX matches confirming 18 distinct archetypes plus variants):

```
c-tracker, c-watch, c-brief, c-prep, c-schedule, c-streak,
c-person, c-reminder, c-quicklog, c-pick, c-offer, c-decision,
c-draft, c-confront, c-reflection, c-openloop, c-permission, c-read
```

The 18 showcase plans in `dashboard/web/lib/plans/showcase/index.ts` use **only** these `c-*` archetypes (plus bridge types: hero, note, footer). The showcase is **100% catalogue-native**.

The composer prompt at [backend/dashboard/compose.py:144-158](../backend/dashboard/compose.py#L144) lists the **legacy** block types as the primary surface:

```
thesis | witness | todo-list | reminders | permission | tracker-grid | footer
```

It mentions other legacy blocks (hero, confrontation, celebration, etc.) sparingly. **It does not name a single `c-*` archetype.**

So:
- Showcase plans use 18 catalogue archetypes
- Composer prompt teaches 7 legacy blocks
- **The two universes don't speak the same language.**
- The LLM composer cannot pick `c-watch`, `c-brief`, `c-streak`, `c-confront`, `c-pick`, `c-draft`, `c-offer`, `c-decision`, `c-reflection` etc. — they are not in its menu.

The action verb declarations (`dashboard/web/lib/plan.ts:21`) — 16 verbs:

```
start_tracker | log_value | complete_pick | snooze_reminder | mark_reminder_done |
dismiss_attention | accept_attention | connect_integration | accept_draft |
decide_option | quick_log | open_relationship | open_news | open_tracker | reply_chip
```

The action handlers in [backend/dashboard/actions.py](../backend/dashboard/actions.py) — 3 wired:

```
accept_attention      → flips OFFERED → LIVE
dismiss_attention     → flips OFFERED → REJECTED
mark_reminder_done    → marks reminder done, recompose
```

**13 of 16 verbs return 501** (`api/dashboard_routes.py:194`). Showcase plans render them as if tappable (sc12 has 3 quicklog chips that all 501; sc16 has accept_draft + decide_option that 501; sc18 has connect_integration that 501).

**Translation: most of the design system you built can't be picked by the brain or acted on by the user.**

### What needs to ship to close the dashboard reachability gap

1. **Teach the composer prompt the 18 archetypes.** Section per archetype with: visual purpose, when to pick it, attention-card mapping, voice rules. ~3 days work, big editorial lift.

2. **Wire the 13 missing verbs.** Each is ~2-4 hours: write the handler, write the side-effect (recompose, reflection log, tracker tick, etc.), write the test. Total ~1 sprint.

3. **Trim or wire — pick one.** If you don't want to wire all 13 yet, narrow the schema to the verbs that exist. Don't render verbs that don't work. Showcase fixtures should be flagged as "v0 design intent, partial implementation" until they all work.

4. **Make the morning trigger recompose the dashboard.** The single highest-leverage UX fix. ~2 hours.

5. **Make every accepted attention recompose silently.** [backend/dashboard/actions.py:130](../backend/dashboard/actions.py#L130) already does this for accept_attention. Extend to dismiss_attention + mark_reminder_done + future log_value etc. ~half day.

6. **Add the WhatsApp-burst-tied-to-fresh-manifest hook.** When manifest changes via worker (not user-tap), fire a "look at your dashboard" burst with a magic link — but only when the change is editorial-significant (e.g., morning recompose, evening recap, mid-day shift after a major signal). ~1 day to design + implement the gating logic.

7. **Replace SSE in-process pubsub with Redis.** ~1 day. Multi-pod-safe.

---

## Part VII · The integration sense gap

The user's framing in this conversation: "If 'she holds your life' is the brand and she only sees Gmail + Calendar + what you actively text her, then most of the user's life is invisible to her."

Donna currently has high-fidelity continuous sense of:
- WhatsApp conversation (the only continuous stream)

Per-event sense of:
- Gmail (push webhooks, can drop)
- Calendar (push webhooks, can drop)

Bootstrap sense of:
- Gmail biography (4 LLM passes at OAuth time, frozen until user re-authorizes)

Thin sense of:
- Photos (one Haiku caption at ingest, then text-only)
- Voice notes (one transcript becomes one chat row, no chunking)
- Documents (text PDFs only; scanned = filename in a row)

**Zero sense of:**
- Drive (the "deck about Q2" doesn't resolve)
- Slack (the conversational tool the user lives in)
- Notion / Linear / GitHub (work tools — though scope cut per `donna/attention/README.md` non-negotiable for "user-organized workspaces")
- World signal (Anthropic shipped, ADBE earnings, friend-launch news)
- Health (sleep, HRV, recovery — `rhythm` field is heuristic-only)
- Location, audio (Spotify), spend (Plaid)

The biography synthesis pipeline is gmail-only. The Living Profile narrative claims comprehensive read; it's actually based on a sliver. Donna doesn't know what she doesn't know — she fabricates confident summaries from limited input.

### The minimum sense-expansion for "she actually knows you"

**Per the conversation we've had**, the answer isn't full data warehousing. It's **summary-shape mirrors**:

| Surface | Mirror what | Skip what |
|---|---|---|
| Gmail | message metadata + bodies of important threads (already done, 30d window) | full body archive of every email |
| Calendar | full events (already done) | — |
| Drive | doc metadata: title, mime, modified, owner, shared_with, parent | doc bodies (lazy-fetch on first recall) |
| Slack | channel list + last-N-message metadata for top channels (DMs) | full message history of every channel |
| (deferred per scope cut) Notion / Linear / GitHub | not v1 | — |

Per integration the work is:
- One mirror table (alembic migration)
- One MirrorSync subclass (cursor-managed sync via Composio drive-changes / Slack conversations.history)
- One backfill on connect (mirrors `bootstrap_30d_important` pattern)
- Recall fanout lane in [backend/memory/retrieval/fanout.py](../backend/memory/retrieval/fanout.py)
- One typed lazy-fetch tool (e.g. `read_drive_doc`)
- 2-3 mirror-aware proposers in [donna/attention/propose.py](../donna/attention/propose.py)
- Webhook routing in [api/composio_webhook.py](../api/composio_webhook.py)

That's ~2 weeks per integration after the first. The first (Drive) is ~3 weeks because it lays the `MirrorSync` infrastructure.

### The "she knows what she doesn't know" piece

Add a `users.living_profile.coverage` JSONB:

```json
{
  "gmail": {"connected_at": "...", "last_sync_at": "...", "freshness_minutes": 5, "scope": "metadata + 30d important", "row_count": 4231},
  "calendar": {"connected_at": "...", "last_sync_at": "...", "freshness_minutes": 5, "scope": "30d ahead + 14d back", "row_count": 287},
  "drive": {"connected_at": null, "scope": "not_connected"},
  "slack": {"connected_at": null, "scope": "not_connected"}
}
```

Render in the prompt under a new `## VISIBILITY` block. So when the user asks about a doc Donna doesn't have visibility on, she says "you haven't connected drive — i'm flying blind on docs. want to fix that?" rather than fabricating from gmail context.

---

## Part VIII · The unified plan to make Donna feel magical

This rolls up the audit + the user's "ideally integrations flow through attention" architecture decision + the "first thing to ship" concrete pick.

### Phase 0 — Reliability + Trust floor (1 sprint, ~$0/mo)

The ground truth has to be trustworthy before any sense-expansion. These are pure plumbing:

| Work | Effort | What it unlocks |
|---|---|---|
| Healthchecks self-host on existing infra | Low | Catches dead-worker silent failures (audit 01) |
| Fix calendar spawner regression | Low | One of the two proactive paths is currently broken (the failing test) |
| Drop Stage 0 dead path + dead params + load_living_profile orphan + STAGE_0_5 simplifications | Low | Removes prompt drift (audit 14) |
| Add `proactive_max_turns` reader OR delete the field | Low | Removes config drift (audit 05) |
| Trim Stage 0 prompt + CAPTURING examples to 1 | Low | Cache savings, prompt clarity |
| Reconcile CLAUDE.md vs code: `stay_silent`, `offer`, `dig_deeper`, `compile_brief` mentioned but missing | Low | Either implement or doc as missing |
| GitHub Actions CI (lint + pytest + alembic dry-run + Promptfoo eval gate over 8-10 canary prompts) | Medium | Catches regressions on every PR |
| Rename `phase-1-usable` → `main`; `LANGSMITH_PROJECT=donna-prod` | Low | Stops mixing dev + prod traces |
| Send-burst schema tightens to match prompt (3-item cap, voice-first enforcement, voice ↔ widget exclusion) | Low | Stops malformed bursts |
| Calendar TZ strip fix; today-window in user-local TZ; morning-trigger UTC fallback | Low | Audit 02 |
| Morning trigger calls `compose_manifest` before `donna_turn` | Low | Single highest-leverage UX fix |
| Magic-link mint hook on `send_burst` for first_message | Low | Audit 17 dead loop |
| Welcome fixture (3 placeholder tiles) for empty-manifest 404 | Low | Audit 17 |
| LP freshness gate in dashboard composer (refuse to render LP > N hours stale) | Low | Stops 24h-stale narrative leaking |
| Drop LP orphan fields (`what_changed_this_week`, `rhythm.typical_quiet_hours`) | Low | Cache + clarity |

### Phase 1 — Sense expansion + Attention unification (2 sprints, ~$30/mo)

This is the structural work that makes "Donna comes to life" possible.

| Work | Effort | What it unlocks |
|---|---|---|
| `mirror_cursors` table + `MirrorSync` base class + `donna-mirrors` Railway role | Medium | Foundation for Drive (and future Slack) |
| Drive ingest (`drive_documents` table + `DriveSync` + `read_drive_doc` lazy-fetch) | Medium | "the deck about Q2" resolves |
| Drive backfill on connect — mirror `bootstrap_30d_important` pattern | Medium | Day-1 Drive sense |
| New mirror-aware proposers in `donna/attention/propose.py`: `DriveShareProposer`, `DriveStaleDocProposer`, `CommitmentDriftProposer`, `QuietRelationshipProposer`, `InboxRhythmProposer` | Medium | The "perfect day" Section I gaps start filling in |
| Migrate `proactive_email_trigger` to emit Attentions instead of ProactiveEvents | Medium | Single dispatcher path; the canonical structure is one |
| Add `kind=fresh_arrival | commitment_drift | quiet_relationship | drive_share | inbox_rhythm | confront` to Attention enum | Low | Surfacing rules per kind |
| Add `surface_rule: ambient | offered | push` column for ambient-state Attentions | Low | "inbox is spiking" feeds prompt without a notification |
| `users.living_profile.coverage` JSONB + `## VISIBILITY` block in system prompt | Low | She knows what she doesn't know |
| `DONNA_PROACTIVE_TIERED=shadow_with_writes` mode (judge runs, ships nothing, **writes ProactivePing rows**) | Medium | Cooldown table populates before mirror→tiered flip |
| Backfill ProactivePing from existing Langfuse traces | Low | Day-of-flip safety |
| Wake `run_proactive_tick` (the active world engine) — `user_watchlists` table + 5-min cron + 3 source adapters (Exa, GDELT, RSS) | Medium | Audit 19 — Donna can finally watch the world |
| Mid-day + evening + late triggers (mirroring morning) | Medium | "Donna initiates" beyond morning |
| In-meeting suppression in arbiter (calendar.now() check) | Low | Don't ping mid-meeting |
| Post-meeting trigger (15-min delay, "how'd it go?") | Low | Captures fresh post-meeting reads |
| Langfuse self-host + per-stage tracing on recall + research + dispatcher | Medium | Audits 08, 14, 16 |
| Helicone proxy for cost cap + budget alerts + caching | Low | Audit 05 |
| GPTCache for research and recall | Low | Audit 08, 09 |

### Phase 2 — Choreography + dashboard archetype unlock (2 sprints, ~$50/mo)

| Work | Effort | What it unlocks |
|---|---|---|
| Composer prompt teaches all 18 catalogue archetypes (per-archetype: visual purpose, when to pick, attention-card mapping, voice rules) | High | The catalogue stops being a museum |
| Renderer enforces archetype types vs free-form blocks | Medium | Quality bar |
| Wire 13 missing action verbs (or trim schema + fixtures to what exists) | Medium-High | Showcase plans become production plans |
| Redis pubsub for SSE backbone (multi-pod safe) | Low | Worker recompose reaches API SSE |
| WhatsApp burst tied to fresh manifest ("look at your dashboard") with editorial gate | Medium | The canonical product moment |
| Cross-source connector (email mentions Thursday 3pm + calendar gap + Drive deck → propose event) | Medium | The "you have 1h, drafting now" prep moment |
| Voice-note as document (WhisperX-style chunked pipeline) | Medium | Audit 11 — "the founder I mentioned in my voice note last Tuesday" works |
| OCR fallback for scanned PDFs (Docling + Tesseract + Chonkie semantic chunker) | Medium | Audit 11 — receipts/contracts work |
| Image embeddings (SigLIP 2 or Voyage multimodal-3) | Medium | Audit 11 — "find the photo of the whiteboard" works |
| R2 wired (env vars exist; no client code) | Medium | Audit 11 — media stops expiring on WhatsApp's CDN |

### Phase 3 — Polish + scale (1 sprint, optional)

| Work | Effort | What it unlocks |
|---|---|---|
| Profile editor at `/dashboard/settings` (name, TZ, voice mode, integrations) | Medium | Audit 17 — user can fix wrong WhatsApp profile_name |
| Onborda 4-step first-dashboard tour | Low | Audit 17 onboarding |
| Landing page with story + screenshots | Medium | Audit 17 marketing |
| Slack ingest (after Drive proves the pattern) | Medium | Sense expansion to second work tool |
| Bitemporal facts read tool ("recall(purpose='historical', at=...)") | Medium | Audit 15 — the bitemporal store stops being orphaned |
| Chat-messages compactor (rolling summarization) | Medium | Audit 15 — append-only forever stops being a problem |
| Transactional outbox for write-fanout hooks | High | Audit 15 — observation can't land in Postgres without reaching Supermemory |

---

## Part IX · The smallest first move (~3 days, proves the new model)

Pick **one** complete vertical slice that proves Attention-as-canonical-structure works end-to-end. The smallest one:

**The "morning that recomposes the dashboard" cut.**

Touch these files:
- [backend/web/proactive/triggers/morning.py:269](../backend/web/proactive/triggers/morning.py#L269) — call `compose_manifest(trigger='morning_check_in')` before `donna_turn`
- [backend/dashboard/compose.py:144-158](../backend/dashboard/compose.py#L144) — add a small section teaching the prompt about `c-confront` and `c-prep` (the two archetypes most likely to surface in a morning briefing for a user with a stakes meeting)
- [backend/dashboard/manifest_events.py](../backend/dashboard/manifest_events.py) — keep the in-process pubsub for now; SSE will work for the user who taps the morning link from the same pod that composed
- [donna/attention/propose.py](../donna/attention/propose.py) — add ONE new proposer: `CommitmentDriftProposer` that reads `email_messages` mirror for "I'll send X by Y" patterns + `open_loops` for matching loops, emits Attention(kind=`commitment_drift`)
- The composer prompt's OFFERED routing — add: `kind=commitment_drift` → `c-openloop` (quote variant, overdue flag) + `accept_attention` action
- Run the morning trigger in dev with a fixture user; verify: Living Profile rebuilds → CommitmentDrift proposer shadows an Attention → promoter promotes → composer renders c-openloop → WhatsApp burst goes out → user taps link → dashboard shows c-openloop card with the same line as the burst → user taps "I did this" → action handler closes the open_loop → recompose → c-openloop is gone

This single slice exercises:
- Attention as canonical structure ✓
- Mirror-aware proposer (reads `email_messages` mirror that already exists from gmail bootstrap) ✓
- Living Profile-driven trigger ✓
- Dashboard recompose tied to morning trigger ✓
- Catalogue archetype reachable from the composer prompt (just one to start) ✓
- Action verb wired (`accept_attention` already works) ✓
- Same editorial line in chat and on dashboard ✓

If it works end-to-end, every other proposer + every other archetype + every other integration follows the same pattern. The system either produces magic or doesn't.

---

## Part X · Closing read

The system isn't broken. Most of the parts are built. The pattern of failure is **disconnection**: parts that exist don't talk to each other.

- Synthesis writes Living Profile but doesn't propose Attentions from what it noticed.
- Proposers shadow but `DONNA_PROACTIVE_OFFER_ACTIVE=1` keeps them dark.
- Email proactive is a parallel path to Attention — same destination, two roads, different judges.
- Catalogue archetypes exist but the composer prompt doesn't know they exist.
- Action verbs exist in the schema but return 501.
- Drive OAuth exists but no ingest, no tools, no proposers.
- Active world engine exists but never runs.
- Morning trigger fires but the dashboard doesn't recompose.
- Cross-source signal exists in 4 separate stores but recall queries 5 of 10.

The user said "Code seems clunky af to me right now" — yes, but it's not bad code. It's underwired code. **The clunk is in the seams between subsystems, not within any one subsystem.**

The fix is sequenced:
1. Phase 0 reliability so trust floor is real
2. Phase 1 sense expansion so Donna sees the user's life
3. Phase 1 Attention unification so every signal flows through one canonical structure
4. Phase 2 choreography unlock so the catalogue archetypes + action verbs go live
5. Then she's Donna.

Not Donna-eventually. Donna in 4-6 sprints if focused. Less if multiple people work parallel slices.

The smallest first move is the morning-recomposes-the-dashboard cut — 3 days, exercises the whole new model end-to-end, and proves the rest is the same pattern repeated.
