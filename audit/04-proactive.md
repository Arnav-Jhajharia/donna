# 04 · Proactive (3 types) + World Engine

You asked for three buckets:
- **User-based** — fires because of something the user said/did
- **Random-based** — Donna reaches out on her own to ask something or check in
- **World-based** — fires because something in the outside world changed

This is exactly how the codebase splits, even though it isn't named this way internally.

## Type 1 — User-based

Fires from user signal: chat, observations, open loops.

| Trigger | Where | Signal | What it produces |
|---|---|---|---|
| **ChatPhraseProposer** | [`donna/attention/propose.py:190`](../donna/attention/propose.py#L190) | regex match in last 24h chat (drinking phrases) | SHADOW TALLY for hydration |
| **ObservationFrequencyProposer** | [propose.py:407](../donna/attention/propose.py#L407) | same observation type ≥3× in 7 days, median gap ≤3d | SHADOW TALLY |
| **DeadlineProposer** | [propose.py:605](../donna/attention/propose.py#L605) | open loop with `due_at` 24-72h out | SHADOW PING |
| **attention_offer source** | [`proactive/sources/attention_offer.py:38`](../proactive/sources/attention_offer.py#L38) | a SHADOW promoted to OFFERED | dispatcher event (ping/hold/drop) |
| **Observation spawner** | [`proactive/spawners/observation.py:31`](../proactive/spawners/observation.py#L31) | drinking_event evening | next-day 09:00 hydration ping (LIVE one-shot) |

These all run in `attention_worker.run_forever`. The new `donna-attention` Railway service we deployed runs this. The proposers create SHADOW attentions; the promoter ticks them and decides whether to surface as OFFERED.

## Type 2 — Random-based (Donna seeks info / checks in)

Single trigger today: **morning_check_in** at [`backend/web/proactive/triggers/morning.py:197`](../backend/web/proactive/triggers/morning.py#L197).

Gates (all must pass):
1. user has ≥3 days of rhythm history (cold-start protection)
2. inside `typical_first_engage_window` ±30 minutes
3. `watch_for_tomorrow` is non-empty
4. not already fired today (`morning_proactive_last_fired_at` < today's 05:00 anchor)
5. user has a phone on file

If gates pass: drafts a prompt from `narrative + today_shape + watch_for_tomorrow`, runs `donna_turn` with `mode=proactive`, sends via WhatsApp.

**Was orphaned until today.** Wasn't called from any worker. Now wired through `synthesis_worker.run_forever` ([line 176](../backend/memory/jobs/synthesis_worker.py#L176)) — and our new `donna-synthesis` Railway service runs that.

**There's no other "random" trigger.** No "Donna checks in midday because it's been quiet for 4 hours". No "Donna asks about your week on Sunday". No "Donna starts a conversation because the user hasn't logged hydration in 3 days, and that's on her watchlist". These would all fit naturally into this bucket but don't exist yet.

## Type 3 — World-based (external signal)

| Trigger | Where | Signal |
|---|---|---|
| **proactive_email_trigger** | [`backend/integrations/proactive_email_trigger.py:151`](../backend/integrations/proactive_email_trigger.py#L151) | inbound Gmail via Composio webhook |
| **CalendarRecurrenceProposer** | [propose.py:100](../donna/attention/propose.py#L100) | recurring titles in calendar (≥2× in 30d) |
| **Calendar spawner** | [`proactive/spawners/calendar.py:71`](../proactive/spawners/calendar.py#L71) | new calendar event via Composio webhook |
| **Spawner worker (24h sweep)** | [`backend/memory/jobs/spawner_worker.py:97`](../backend/memory/jobs/spawner_worker.py#L97) | catches new calendar events Composio missed |

The email trigger scores incoming Gmail with `email_importance.score_email`. If ≥0.5, it becomes a `ProactiveEvent` and gets routed through the dispatcher.

The calendar spawner detects "this looks like a stakes meeting" or "this looks like a social event" and queues a prep ping 5–60 min before fire time.

## Dispatcher + judge + arbiter

The router in the middle: [`proactive/dispatcher.py:496`](../proactive/dispatcher.py#L496)

Pipeline:
1. **Arbiter** ([`backend/integrations/proactive_rate_limit.py:159`](../backend/integrations/proactive_rate_limit.py#L159)) — quiet hours, active chat, topic cooldown 30min, global cooldown 30min, daily quota 3/day. Returns `allowed | reason`.
2. **Tier 2 Judge** ([`proactive/judge.py`](../proactive/judge.py)) — Haiku 4.5 LLM call. Returns `{action: ping|hold|drop, register: alert|soft, draft, tie_in, needs_tools, reasoning}`.
3. **Voice validator** — checks no uppercase, no emoji.
4. **Escalate to brain** if `needs_tools=True` or judge failed.
5. **Ship** (WhatsApp + ChatMessage + ProactivePing row) or **hold** (pending_proactive_notes) or **drop** or **mirror_log**.

## The "world engine" question

You called this out separately. What I read in the codebase:

There is no module named "world engine". What plays that role today is:
- **Composio webhooks** ([`api/composio_webhook.py`](../api/composio_webhook.py)) — single inbound funnel for Gmail, Calendar, (eventually Slack/Drive/etc.)
- **Per-source handlers** — `proactive_email_trigger.py`, `proactive/spawners/calendar.py` parse the events and decide whether to surface
- **Event types** are matched by string (`"gmail.new_message"`, `"calendar.event_created"`, etc.)

So "world engine" is really: webhook → per-source spawner → ProactiveEvent → dispatcher. There's no central registry, no schema for "what kinds of world events do we care about", no batching, no fanout to brain.

The web pipeline ([`backend/web/`](../backend/web/) — `client.py`, `expansion.py`, `pipeline.py`, `search.py`) is a **separate system** for in-conversation web search and agentic research. It's not connected to proactive triggering. There's no scheduled "what happened in Aarav's interest space today?" sweep that would feed proactive nudges.

So the world engine for proactive purposes is reactive (responds to webhooks), not active (doesn't scan the world on a schedule). Real watch behaviour (e.g. "tell me when ADBE moves >2%") is not implemented.

## The shadow-mode flag

You may remember a flag like `USE_NEW_PROACTIVE=shadow`. The actual flag is **`DONNA_PROACTIVE_TIERED`** (not the same name). Default is unset = mirror mode.

- **Mirror mode** (default): dispatcher runs, logs the decision, returns `mirror_logged`. Doesn't write `ProactivePing`. Doesn't send. Legacy brain path runs in parallel.
- **Gated mode** (`=1`): dispatcher actually ships. Writes `ProactivePing` (which feeds cooldown/quota). Brain only entered on escalation.

There's also `DONNA_PROACTIVE_OFFER_ACTIVE=1` which gates whether OFFERED attentions get an active push or stay passive (just appearing in the dashboard).

## Production state — what actually fires today

| Trigger | Code? | Wired? | Sends to user? |
|---|---|---|---|
| Email proactive | ✓ | ✓ Composio webhook | ✓ legacy brain path |
| Morning check-in | ✓ | ✓ via new `donna-synthesis` | should fire today onwards |
| Chat-phrase proposer | ✓ | ✓ via new `donna-attention` | shadows attentions, no surface yet |
| Obs-frequency / deadline proposers | ✓ | ✓ via new `donna-attention` | shadows attentions, no surface yet |
| Calendar spawner (per-event) | ✓ | ✓ Composio webhook | ✓ if hooked |
| Calendar 24h sweep | ✓ | ⚠️ requires `DONNA_SPAWNERS=1` (unset on prod) | ✗ |
| Observation spawner | ✓ | ✓ post-commit hook on `log_observation` | ✓ |
| Attention LIVE fires | ✓ | ✗ no schedule worker deployed | ✗ |
| Attention OFFERED active push | ✓ | ✗ requires `DONNA_PROACTIVE_OFFER_ACTIVE=1` | ✗ |

**The dispatcher is in mirror mode in prod.** That means `ProactivePing` rows aren't being written. Cooldown and daily-quota tracking depend on that table. So if mirror flips to gated tomorrow without a backfill, you risk re-firing on every email thread because the cooldown table is empty.

## Critical risks

1. **No active world-engine watching.** Donna can't actually "watch ADBE" or "watch the Poke launch" today. The Watch archetype in the dashboard is real visually but has no signal feeding it.
2. **Proposers shadow without promotion.** If the promote pass doesn't run (or doesn't find evidence to promote), candidates pile up in SHADOW forever and the user never sees them.
3. **No "Donna initiates conversation" loop** beyond morning. There's no "you haven't spoken in 6 hours and you said you'd run today" check-in.
4. **Calendar spawner only on webhook.** If Composio is down for an hour, those events ingest but don't spawn. The 24h sweep covers this — but only if `DONNA_SPAWNERS=1`, which is unset.

## My opinion

The proactive architecture is the most thoughtful piece of design in the codebase. Tier 1 scoring (cheap, deterministic) → Tier 2 judge (LLM) → escalation to brain (tools) is the correct shape. Voice validation as a separate pass is right. The arbiter with quiet hours + active chat + cooldown is right.

But the actual surface area of "Donna proactively does something" is narrow today:
- Email proactive (works, but mirror-mode)
- Morning briefing (just got wired today)
- Calendar prep (works for new events)

That's it. The user-facing promise of "high-agency thinking partner who notices things" — currently barely fires.

The biggest unbuilt thing is the **active world engine** — a scheduler that wakes up and asks "what changed in Aarav's interest space?". Without it, the Watch archetype is decorative. And without spawning new "random" check-ins beyond morning, Donna doesn't feel like she's choosing to reach out. She feels like a polite system that responds to webhooks.

**For Donna's vision** — Donna is supposed to be the partner who calls you, not the assistant who waits for your call. The plumbing for that is mostly there. The active triggers are missing.

## Verdict

Architecture: ✅ excellent
Production: ⚠️ mirror mode, half the triggers dark
Gap to vision: large — Donna is reactive today, not active. Closing this is the difference between "she's clever" and "she's Donna."
