# Proactive Engine — Tiered Judgment + Hold Lane (v1)

**Date:** 2026-04-26
**Status:** Design
**Owner:** Bharat

## Why this exists

Donna's proactive surface today is wired but not unified, and it overspends on the wrong axis. Three independent paths (gmail webhook → email trigger, schedule worker → attention fire, attention promote → OFFERED) each invoke the full brain when they decide to surface something. Each path runs its own gate. There is no shared "hold this for next user touch" lane.

Concretely:

- Every email that scores >= 0.5 invokes a full Sonnet 4.6 proactive turn (USER MODEL + TODAY + RECENT CHAT + tool loop up to 12 steps). Per-fire cost is in the 5–10¢ range. At plausible volume (~30–50 emails/user/day pass the deterministic scorer) this is multiple dollars per user per day for inbox triage alone.
- Reminders fired by `schedule_worker.run_once` for legacy `DonnaSchedule` rows (no `attention_id`) bypass the brain entirely and bypass the unified rate limiter. A 3am reminder fires at 3am, voice-unfiltered.
- `proactive_rate_limit.can_fire_proactive` already implements quota + cooldown + quiet hours over a shared `ProactivePing` table, but only the email path calls it. Attention fires and promotions don't consult it.
- There is no surface for "drafted but not pushed" — the most useful register, where most decisions should land. OFFERED attentions partially fill this only for proposed structures, not for ad-hoc moves like "luca replied while you were in your meeting."

This v1 introduces:

1. **Tier 2 — a cheap judge-and-author** (single Haiku 4.5 call) between the deterministic scorer and the full brain. Decides ping / hold / drop and drafts the message inline.
2. **The hold lane** — a `pending_proactive_notes` table that captures Tier 2's `action=hold` outputs and surfaces them in the user's next reactive turn.
3. **Unified arbiter** — every proactive path funnels through `proactive_rate_limit`, extended with per-topic dedup and an "active conversation" check.
4. **Standardized event envelope** — a single `ProactiveEvent` shape so every source looks alike to the judge.

Net effect: ~10× cost reduction on the email path at steady state (math in **Cost targets** below), a real "she leads with what accumulated" UX, and the consolidation that lets the next layer (pattern noticer, multi-source synthesis) plug in cleanly.

## Non-goals (v1)

- **Pattern noticer / non-event-driven trends.** Trend detection (ghosting, momentum heating up, streak about to break) is a separate proposer that runs on a slow timer over biography + open_loops + observations. Out of scope for this spec, but the unified arbiter and hold lane are designed to host it.
- **Calendar event triggers.** Calendar webhooks ingest events but don't currently fire proactive turns. Adding that goes through this spec's pipeline once landed; the actual subscription wiring is a follow-up.
- **Active push of OFFERED attentions.** OFFERED attentions remain passive (rendered in context, accepted via tool call). A separate spec covers active push.
- **Collapsing `DonnaSchedule` and `Attention` storage.** Same primitive in two homes; collapse deferred. v1 keeps both, but every fire that has an `attention_id` flows through the new pipeline. Legacy reminders (`attention_id IS NULL`) keep their direct-send path until the storage collapse spec lands.
- **Cross-source synthesis prompt rewrite.** The Tier 3 brain's proactive prompt isn't being touched in this spec. Tier 2 is doing the cross-source work for the common case; Tier 3 inherits Tier 2's draft as a hint when escalated.
- **New surfaces beyond WhatsApp + dashboard.** Voice, email, calendar invites as outbound channels — out of scope.

## Architecture

```
[ANY TRIGGER]
  ├─ gmail webhook         (api/composio_webhook.py)
  ├─ attention scheduled fire (donna/attention/firing.py)
  ├─ attention shadow → OFFERED transition (donna/attention/promote.py)
  └─ (future) calendar event, slack mention, etc.
        │
        ▼  produces a canonical ProactiveEvent
  ┌────────────────────────────────────────────────┐
  │ Tier 1 — deterministic scorer (per-source)     │
  │  - email_importance.score_email                │
  │  - attention.dry_run hit detection             │
  │  - calendar event delta heuristics (future)    │
  └────────────────────────────────────────────────┘
        │  score >= threshold (else drop, no trace)
        ▼
  ┌────────────────────────────────────────────────┐
  │ Unified arbiter — can_fire_proactive(...)       │
  │  - daily quota   (3/day)                       │
  │  - cooldown      (30m global, 30m per topic)   │
  │  - quiet hours   (sleep_time / wake_time)      │
  │  - active-chat   (5m since last user message)  │
  └────────────────────────────────────────────────┘
        │  allowed
        ▼
  ┌────────────────────────────────────────────────┐
  │ Tier 2 — cheap judge-and-author (Haiku 4.5)    │
  │  inputs: USER MODEL, TODAY, recent chat,        │
  │          ProactiveEvent, signals                │
  │  output: { action, register, draft, tie_in,    │
  │            needs_tools, reasoning }             │
  └────────────────────────────────────────────────┘
        │           │              │
   ping │     hold  │         drop │
        │           │              │
        ▼           ▼              ▼
   needs_tools?   pending_      ProactivePing
        │         notes table    (suppressed_reason
   no  │         (insert)         = "tier2_drop:<reason>")
        │
        ▼
   send drafted        ┌─ yes ─→ Tier 3 — full brain
   directly (ship)     │         (donna_turn, mode=proactive)
                       │         receives Tier 2 draft as hint
                       │
                       ▼
                   send_burst → WhatsAppChannel
```

The unified arbiter sits **before** Tier 2 — we don't pay for the LLM call if we already know we won't fire. The cheapest gate runs first.

## Components

### `ProactiveEvent` envelope (new)

```python
# proactive/events.py
from dataclasses import dataclass, field
from typing import Any, Literal

ProactiveSource = Literal[
    "email", "attention_fire", "attention_offer", "calendar"
]

@dataclass(frozen=True)
class ProactiveEvent:
    user_id: str
    source: ProactiveSource
    source_ref: str            # gmail_message_id | attention_id | event_id
    topic_key: str             # for dedup; defaults to source_ref
    payload: dict[str, Any]    # source-specific shape, normalized
    signals: dict[str, Any] = field(default_factory=dict)
                               # Tier 1 output: {score, signals, ...}
```

Each source has a small adapter (`proactive/sources/email.py`, `attention.py`, etc.) that produces this envelope from its native trigger payload. Replaces the bespoke prompt construction currently in `proactive_email_trigger._format_trigger_prompt` and `attention.firing.build_fire_prompt`.

### Tier 2 — judge-and-author (new)

```python
# proactive/judge.py
async def judge_event(event: ProactiveEvent) -> JudgeResult: ...

@dataclass(frozen=True)
class JudgeResult:
    action: Literal["ping", "hold", "drop"]
    register: Literal["alert", "soft"] | None  # only set when action=ping
    draft: str | None                          # Donna's drafted message
    tie_in: list[str]                          # references to user state
                                               # ('antler-call-thu', 'deck-v3')
    needs_tools: bool                          # escalate to Tier 3
    reasoning: str                             # short, for telemetry
    raw_response: str                          # raw model output for audit
```

**Prompt structure:**

```
SYSTEM:
  <donna voice charter (lowercase, no em dashes, etc)>
  <judgment criteria — when to ping vs hold vs drop>
  <output schema (strict JSON)>

USER:
  <USER MODEL block>          # already exists, load_user_model_block
  <TODAY block>               # already exists, load_today_block
  <RECENT CHAT (last 5 lines)>
  <PROACTIVE EVENT>
    source: email
    source_ref: <gmail_message_id>
    payload:
      from: ...
      subject: ...
      body_excerpt: ... (600 chars max)
    signals:
      score: 0.7
      signals: ['biography_relationship', 'open_loop_match']

  Decide: ping / hold / drop.
  If ping or hold: draft the message in donna's voice.
  If you'd want to call a tool to decide better, set needs_tools=true.
```

**Model:** `claude-haiku-4-5-20251001` (Donna's existing offline-eval model).

**Token budget:** 1500–2500 in, 200–400 out. ~$0.001–0.003 per call at current rates.

**Voice enforcement:** prompt-based + a deterministic post-validator (`proactive/voice_validator.py`) that:

- Strips em dashes (`—`, `–` → ` `)
- Strips semicolons (replaces with `.`)
- Computes uppercase-character ratio over alphabetic chars; if >5%, flag and re-author with explicit "lowercase only" instruction. Reasoning: proper nouns and acronyms (Antler, Y, AI) are legitimate uppercase; we don't try to identify them, we just keep the ratio in check.
- Flags emojis → re-author once with explicit "remove emoji" instruction; if still present, fall back to Tier 3

The validator runs before any draft reaches WhatsApp or the hold lane.

**Failure modes:**

- Timeout (>3s) → fall back to Tier 3
- Malformed JSON → re-parse with structured-output retry, then fall back to Tier 3
- `action=ping` with no draft → fall back to Tier 3
- Voice validator can't repair → fall back to Tier 3

In all fallbacks, telemetry tags the event so we can tune.

### `pending_proactive_notes` table (new)

```sql
CREATE TABLE pending_proactive_notes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         text NOT NULL REFERENCES users(id),
  source          text NOT NULL,
                                  -- 'email' | 'attention_fire' | 'attention_offer' | 'calendar'
  source_ref      text,           -- gmail_message_id | attention_id | event_id
  topic_key       text,           -- matches ProactiveEvent.topic_key for dedup
  draft           text NOT NULL,  -- Donna's drafted message
  tie_in          jsonb NOT NULL DEFAULT '[]',
  reasoning       text,
  status          text NOT NULL DEFAULT 'pending',
                                  -- pending | delivered | expired | superseded
  created_at      timestamptz NOT NULL DEFAULT now(),
  delivered_at    timestamptz,
  expires_at      timestamptz NOT NULL DEFAULT (now() + interval '12 hours')
);
CREATE INDEX idx_pending_user_status ON pending_proactive_notes(user_id, status, created_at DESC);
CREATE INDEX idx_pending_topic ON pending_proactive_notes(user_id, topic_key) WHERE status = 'pending';
```

**Lifecycle:**

1. Tier 2 returns `action=hold` → row inserted with status=`pending`, draft set, expires_at = now + 12h.
2. Insert path checks for an existing pending row with same (user_id, topic_key); if present, marks the older row `superseded` and writes the new one. Avoids stacking multiple notes about the same thread.
3. On every reactive turn, `context_builder.render_turn_context` reads up to 5 pending rows for the user (newest-first), renders a `## PENDING NOTES` block:
   ```
   ## PENDING NOTES
   structures donna queued while user was away. lead with them if relevant.
   - <id> | email | luca replied. wants thursday or friday. | tie_in: [antler-call-thu, deck-v3]
   ...
   ```
4. The brain dismisses notes explicitly via a new tool: `clear_pending_note(note_id, reason)`. Reasons: `delivered` (the burst addressed it), `irrelevant` (no longer worth surfacing), `superseded_by_user` (user brought it up themselves first). The brain's system prompt instructs it to clear notes it consumes. We do not auto-detect overlap in v1 — too brittle, too easy to get wrong silently.
5. A nightly sweep (or hourly) marks `pending` rows past `expires_at` as `expired`. Default TTL: 12h.
6. `pending` rows are visible on the dashboard moments page (a small "queued" tray) so the user can see what Donna is sitting on.

**Why 12h TTL:** longer than a typical work session, shorter than next-day staleness. Tunable per source if needed.

### Unified arbiter — `proactive_rate_limit` extension

Existing surface:

```python
async def can_fire_proactive(user_id: str, source: str, now=None) -> FireDecision: ...
async def record_ping(user_id: str, source: str, message_ref, ...) -> None: ...
```

Extensions:

```python
async def can_fire_proactive(
    user_id: str,
    source: str,
    *,
    topic_key: str | None = None,
    now: datetime | None = None,
) -> FireDecision: ...
```

New checks (in order):

1. **Quiet hours** (existing).
2. **Active conversation:** if the user sent a message in the last 5 minutes (`max(ChatMessage.created_at WHERE role='user')`), deny with `reason="active_chat:Xs"`. Reactive turn will surface things naturally.
3. **Per-topic cooldown:** if `topic_key` is set, query `ProactivePing` for any prior fire on the same `topic_key` in the last 30 minutes. Deny with `reason="topic_cooldown:Xs"`.
4. **Global cooldown** (existing, 30 minutes).
5. **Daily quota** (existing, 3/day).

`ProactivePing` schema gets a new column:

```sql
ALTER TABLE proactive_pings ADD COLUMN topic_key text;
CREATE INDEX idx_pings_user_topic_fired
  ON proactive_pings(user_id, topic_key, fired_at)
  WHERE topic_key IS NOT NULL;
```

`record_ping` gets the new param. Backfill is unnecessary — old rows just have `topic_key IS NULL` and don't participate in topic-cooldown checks.

### Tier 3 — full brain (existing, escalation only)

`donna_runtime.brain.donna_turn(state, cfg)` with `mode="proactive"` is unchanged. The proactive trigger prompts in `proactive_email_trigger._format_trigger_prompt` and `attention.firing.build_fire_prompt` are extended with one new section:

```
TIER 2 PROPOSAL
action: ping
register: alert
draft: "luca replied. wants thursday or friday."
tie_in: [antler-call-thu, deck-v3]
reasoning: <short>

You can ship this draft as-is via send_burst, or use your tools (recall, list_calendar, ...) to refine. The draft is a hint, not a constraint.
```

When does Tier 3 fire?

- Tier 2 explicitly returns `needs_tools=true` (e.g., wanted to verify whether the user already replied via a Composio gmail-thread lookup).
- Tier 2 fails (timeout, malformed output, voice violation past one repair).
- Configurable: `register=alert` AND `DONNA_PROACTIVE_ALERT_ALWAYS_BRAIN=1` (off by default; an escape valve if we find Tier 2 mishandling alerts in production).

**The flow when Tier 2 ships directly:** Tier 2 returns ping → arbiter is already passed → render the draft via `delivery.messages.TextMessage(body=draft)` → `WhatsAppChannel.send_many` → write `ChatMessage(role="assistant", is_proactive=True)` and `ProactivePing(topic_key=...)`. No SDK loop. No tool budget. Just ship.

### Source adapters (new)

Each path produces a `ProactiveEvent` from its native trigger:

```python
# proactive/sources/email.py
def make_event(user_id: str, msg: NormalizedGmailMessage, score: ScoreResult) -> ProactiveEvent:
    return ProactiveEvent(
        user_id=user_id,
        source="email",
        source_ref=msg.gmail_message_id,
        topic_key=msg.thread_id or msg.gmail_message_id,
        payload={
            "from_address": msg.from_address,
            "from_name": msg.from_name,
            "subject": msg.subject,
            "body_excerpt": (msg.body_text or msg.snippet or "")[:600],
        },
        signals={"score": score.score, "signals": score.signals},
    )

# proactive/sources/attention_fire.py — analogous, source="attention_fire"
# proactive/sources/attention_offer.py — analogous, source="attention_offer"
```

### Dispatcher (new)

```python
# proactive/dispatcher.py
async def dispatch(event: ProactiveEvent) -> DispatchOutcome:
    decision = await can_fire_proactive(
        event.user_id, event.source, topic_key=event.topic_key,
    )
    if not decision.allowed:
        await record_ping(
            event.user_id, event.source, event.source_ref,
            topic_key=event.topic_key,
            suppressed_reason=decision.reason,
        )
        return DispatchOutcome.suppressed(decision.reason)

    judge = await judge_event(event)

    if judge.action == "drop":
        await record_ping(
            event.user_id, event.source, event.source_ref,
            topic_key=event.topic_key,
            suppressed_reason=f"tier2_drop:{judge.reasoning[:80]}",
        )
        return DispatchOutcome.dropped(judge)

    if judge.action == "hold":
        await insert_pending_note(event, judge)
        return DispatchOutcome.held(judge)

    # action == ping
    if judge.needs_tools:
        return await escalate_to_brain(event, judge)
    return await ship_draft(event, judge)
```

`ship_draft` writes the assistant ChatMessage row, sends via `WhatsAppChannel`, and records the ping with `topic_key`.

`escalate_to_brain` builds the proactive trigger prompt with the Tier 2 proposal embedded, calls `donna_turn` in proactive mode, and lets the existing brain pipeline take over.

## Flow walkthrough — gmail email

Before:

```
gmail webhook → ingest → maybe_surface_email → score → can_fire_proactive
  → donna_turn(state, mode=proactive) → brain decides → send_burst
```

After:

```
gmail webhook → ingest → email_source.make_event(msg, score)
  → dispatcher.dispatch(event)
       → can_fire_proactive(topic_key=thread_id)  [arbiter]
       → judge_event(event)                        [Tier 2]
       → ship_draft / hold / drop / escalate
```

The full brain runs only on the ~5% of events Tier 2 escalates.

## Flow walkthrough — scheduled attention fire

Before:

```
schedule_worker.run_once → fire_attention_via_brain(row) → donna_turn(...)
  → brain decides whether to send → send_burst
```

After:

```
schedule_worker.run_once → attention_fire_source.make_event(row)
  → dispatcher.dispatch(event)
       → arbiter (with topic_key=attention_id)
       → Tier 2 (same judge, different prompt framing — "scheduled fire,
                 still relevant?")
       → ship_draft / hold / drop / escalate
```

Notable: the `hold` action is meaningful here too. A reminder for "stretch break" that fires at 3pm but you're in a meeting → Tier 2 sees the calendar event, holds the note, surfaces it when the meeting ends.

## Flow walkthrough — attention promotion

Before:

```
promote.run_shadow_cycle → tick + classify → if promotion_hits >= 2 → status=OFFERED
  → render_offered_attentions_block injects passively into next reactive turn
```

After (additive, doesn't break existing):

```
promote.run_shadow_cycle → ... → status=OFFERED
  → attention_offer_source.make_event(attention)
  → dispatcher.dispatch(event)
       → Tier 2 decides whether to ping the offer actively or leave it passive
       → if ping: draft is the offer card; arbiter governs whether to push
```

The existing passive behavior remains the default. Tier 2 just gets to decide when to escalate to active push — when an OFFER is high-leverage and the user is reachable.

## Voice and content

Voice rules (from CLAUDE.md, propagated to Tier 2's system prompt):

- Lowercase. Always.
- No em dashes. No semicolons.
- No emojis. No markdown.
- Sharp, specific, high-agency. Never "I understand" or "Great question."
- Mirrors the user's slang and pace where appropriate.
- When she doesn't know: say so. Do not fabricate.

Tier 2 prompt includes 4–6 in-domain few-shot examples covering ping/hold/drop and showing the voice. Examples are versioned — `proactive/prompts/judge_v1.md` — so we can iterate on the prompt without touching the harness.

The `voice_validator` is a defensive net for prompt drift, not a substitute for the prompt being right.

## Cost targets

| Tier | Per-fire cost | Share of events |
| --- | --- | --- |
| 1 — scorer | 0¢ | 100% (filters most before this engine runs) |
| Arbiter | 0¢ | 100% |
| 2 — judge | $0.001–0.003 | ~95% of events that pass arbiter |
| 3 — brain | $0.05–0.10 | ~5% (escalations) |

Email path, per user per day at steady-state assumption (50 events past Tier 1, ~30 pass arbiter, ~28 resolved at Tier 2, ~2 escalate):

- Today: ~30 × $0.07 = **$2.10**
- After: (28 × $0.002) + (2 × $0.07) = **$0.20**

10× reduction on the email path alone. The bigger unlock is qualitative — the hold lane changes the UX shape, not just the cost shape.

## Migration plan

**Phase 0 — scaffold (no behavior change):**

1. Create `proactive/` package: `events.py`, `dispatcher.py`, `judge.py`, `voice_validator.py`, `sources/email.py`, `sources/attention_fire.py`, `sources/attention_offer.py`.
2. Add `pending_proactive_notes` table (new alembic migration).
3. Add `topic_key` column to `proactive_pings` (alembic).
4. Add `judge_v1.md` prompt with seed examples.

**Phase 1 — mirror mode:**

5. Wire the email path so it calls `dispatcher.dispatch(event)` AND continues to call the existing `donna_turn` proactively. Both run, both log. Tier 2's decision goes to telemetry only — actual ship still goes through the brain.
6. Build an offline diff harness: replay 100 production-fire events through Tier 2, compare its draft against what the brain actually shipped. Tune the prompt.

**Phase 2 — cutover (email):**

7. `DONNA_PROACTIVE_TIERED=1` flips the email path to ship Tier 2 directly when `action=ping` and `needs_tools=false`. Brain handles the rest.
8. Holds start writing to `pending_proactive_notes`.
9. `context_builder` starts reading the pending block.

**Phase 3 — extend:**

10. Wire `attention_fire` source through the dispatcher (replace `fire_attention_via_brain`'s direct brain call with dispatcher).
11. Wire `attention_offer` source. Default decision: passive (matches existing behavior). Active push gated on a flag.

**Phase 4 — clean up:**

12. Remove the bespoke trigger-prompt formatters in `proactive_email_trigger` and `attention/firing` (now produced by source adapters).
13. `proactive_email_trigger.maybe_surface_email` becomes a thin shim over `dispatcher.dispatch(email_source.make_event(...))`.

Each phase is independently revertible. Phase 1 can run in production for a week to gather signal before Phase 2 flips the switch.

## Failure modes

| Scenario | Behavior |
| --- | --- |
| Tier 2 timeout | Fall back to Tier 3 (full brain) for this event. Telemetry logs `tier2_timeout`. |
| Tier 2 malformed JSON | One structured-retry, then fall back to Tier 3. |
| Tier 2 returns `action=ping` with no draft | Treat as malformed; fall back to Tier 3. |
| Voice validator can't repair draft | Fall back to Tier 3. |
| `pending_proactive_notes` insert fails | `action=hold` collapses to `action=drop`. Telemetry logs `hold_insert_failed`. |
| Arbiter DB unavailable | Deny by default. Telemetry logs `arbiter_unavailable`. Better silent than spam. |
| `ProactivePing.topic_key` column missing (pre-migration) | Code tolerates `None` topic_key — no per-topic cooldown until migration applied. |

## Testing strategy

- **Unit:** prompt rendering, JSON parsing, voice validator, dispatcher branches, hold-lane lifecycle.
- **Integration:** event → dispatcher → dispatch outcome end-to-end, with Postgres + a mock judge.
- **Eval suite:** 50 hand-curated `ProactiveEvent` fixtures with expected `action` (ping/hold/drop). Tier 2 must agree on >= 90%.
- **Smoke:** end-to-end gmail webhook → dispatcher → ship/hold; live small-scale trial in Phase 2.
- **Regression:** mirror-mode A/B logs from Phase 1 are replayed in CI to detect drift.

Coverage target: 80%+ on the new `proactive/` package per the existing repo standard.

## Out of scope (future specs)

- **Pattern noticer.** Periodic scan of biography + open_loops + observations for ghosting / momentum / streak risk. Plugs in as a new `ProactiveEvent` source (`source="pattern"`) once the engine is ready to host it.
- **Calendar event triggers.** Webhook already ingests events. A small adapter that maps "new important event scheduled in next 24h" → `ProactiveEvent(source="calendar")`.
- **Active offer push.** OFFERED attentions today wait for reactive surfacing. A separate spec for actively pushing high-leverage offers.
- **DonnaSchedule + Attention storage collapse.** Same primitive in two homes; collapse spec covers data model and migration.
- **Cross-source synthesis prompt rewrite.** Tier 2 does single-event synthesis well. Multi-event ("3 things accumulated, weave them") is a separate prompt-engineering pass.
- **Voice channel proactive.** Proactive voice notes / voice calls — different latency profile, different consent model, different spec.

## Open questions for review

1. **Quiet hours fallback when facts aren't set.** Today: no quiet hours apply. Should v1 default to a conservative "midnight to 7am local" when `sleep_time`/`wake_time` are unset? Tradeoff: safer onboarding vs unwanted suppression for users who actually want late-night signal.
2. **Tier 2 prompt versioning.** Single `judge_v1.md` vs per-source prompts (`judge_email_v1.md`, `judge_attention_v1.md`). Single prompt is more economical but may dilute per-source context discipline. Recommend single prompt with source-conditional sections.
3. **Hold lane TTL.** 12h proposed default. Should it be configurable per source? E.g., a calendar-derived hold ("you have antler in 30") naturally expires faster than an email hold.
4. **Voice validator strictness.** Strip-and-ship vs reject-and-fallback. Recommend strip-and-ship for em-dash/semicolon (mechanical) and reject-and-fallback for emoji (signal of deeper drift).
