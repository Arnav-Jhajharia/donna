# Proactive Brain Redesign — speech-act-aware Tier 2, fat-contract Tier 3, unified pipeline

**Date:** 2026-05-04
**Status:** Design
**Owner:** Bharat
**Supersedes parts of:** [2026-04-26-proactive-engine-design.md](./2026-04-26-proactive-engine-design.md)

## Why this exists

Donna's proactive surface is unreliable in the moment that matters most: when the model has to decide what to ship to the user, in her voice, without breaking trust. The 2026-04-26 design landed the three-tier scaffold (deterministic scorer → Haiku judge-and-author → full brain re-entry) and a hold lane, and that frame is still right. But two failures emerged.

**First, mirror mode forces every fire through Tier 3.** With `DONNA_PROACTIVE_TIERED` unset in prod, Tier 2's drafts are advisory. The actual ship still routes through `donna_runtime.brain.donna_turn` with `mode="proactive"`, using a thin directive prompt (`donna/attention/firing.py:build_fire_prompt` or `proactive/dispatcher.py:_build_escalation_prompt`). The directive carries `{question}`, `{cadence}`, `{from/subject/body_excerpt}` — and that's it. The brain has to re-decide everything from a payload that strips out the spec, the day's history, prior touches, and fresh signal. It breaks.

**Second, System B has diverged into a parallel pipeline.** The LP-driven proactive web search (`backend/web/proactive/`) — built post-2026-04-26 — has its own judge, its own delivery, its own daily cap, its own dedup ledger, and its own per-tick `delivery_mode`. It bypasses `proactive/dispatcher.py` entirely. The promise of "one pipeline for proactivity" is no longer true on disk.

This spec consolidates both. Net effect:

1. **System B becomes a source, not a pipeline.** It still does LP-driven query gen + Exa fetch, but each hit emits a `ProactiveEvent` into the unified dispatcher. Daily cap, dedup, judge, delivery, and shadow/live mode unify.
2. **Tier 2 becomes speech-act-aware.** Five distinct speech acts (`dont_forget`, `heads_up`, `i_noticed`, `now_the_moment`, `thought_youd_want`), each with its own posture, threshold, register, and draft conventions, composed into one shared scaffold prompt.
3. **Tier 3 becomes a fat-contract editorial brain.** Different mode, different system prompt, narrow tool palette, 11-block input contract that bakes prior touches / DAY view / pending notes / user state / fresh signal into the prompt instead of asking the model to fetch them.
4. **Mirror mode retires** as part of the migration, with a phased gated rollout.

## Non-goals (v1)

- **Dashboard recompose-on-ambient-fire.** Ambient fires (`push=False`) currently leave the dashboard manifest stale until the next reactive turn. Adding `_spawn_recompose` to the unified ship path + new compose inputs (`proactive_fires_today`, `pending_proactive_notes`, longitudinal observation summary) is deferred to a separate spec. Not blocking the proactive redesign.
- **Voice channel (donna-voice).** Out of scope.
- **Active push of OFFERED attentions.** Still tracked in [2026-04-26-proactive-engine-design.md](./2026-04-26-proactive-engine-design.md). Out of scope here.
- **Pattern noticer (cross-source trends like "ghosting" detection).** Out of scope. Will plug into the unified arbiter + hold lane once landed.
- **Collapsing `DonnaSchedule` and `Attention` storage.** Same primitive, two homes. Out of scope.
- **Bitemporal facts wiring.** Long-standing dead code. Separate cleanup.
- **External-side-effect Tier 3 actions** (auto-replying to email, booking calendar slots, Composio actions). Tier 3 is editorial — those need the user in the loop, which is the reactive brain's job.

## Architecture

```
              [QUEUE WRITES]                    [LIVE SENSORS]
              user explicit attend()             gmail webhook
              brain anticipation                 calendar change
              post-turn reminder hook            schedule fire due
              proposers / spawners               System B per-hit emission
                       │                                │
                       └────────┬───────────────────────┘
                                ▼  ProactiveEvent (with speech_act)
                       Tier 1: deterministic scorer
                       (per-source, cheap, no LLM, drops noise)
                                │
                                ▼
                       Unified arbiter
                       (cooldown / quota / quiet hours /
                        active-chat / DAILY CAP / dedup)
                                │
                                ▼
                       Tier 2: speech-act-aware judge-and-author
                       (Haiku 4.5, ONE scaffold + per-act block)
                       output: { action, register, draft, tie_in,
                                 channel_hint, reclassify_speech_act,
                                 needs_tools, reasoning }
                                │
                       ┌────────┼─────────┬────────┐
                       │        │         │        │
                  ping (clean) hold     drop    needs_tools | empty_draft |
                  ship draft   pending  log     validator_fail | stakes_aware |
                       │       notes            hold_ambiguity | tier2_failed
                       │       table              │
                       ▼                          ▼
                  Unified ship             Tier 3: editorial brain
                                           (Sonnet 4.6, mode="proactive_tier3")
                                           FAT INPUT CONTRACT (11 blocks)
                                           NARROW TOOL PALETTE (6)
                                                    │
                                                    ▼
                                           ship | reshape | hold | kill | skip
```

### Two pillars

1. **Auto-queue rich.** Every queue write (BRAIN tool, post-turn hook, proposer, sensor) carries enough context that the consumer at fire time has what it needs.
2. **Firing-time model perfect for the task.** The model handling each fire is sized and prompted to the *speech act* — `dont_forget` ≠ `i_noticed` ≠ `heads_up`. Each act has its own meaning of "wild Donna":
   - `dont_forget` — wildly reliable, never misses
   - `heads_up` — wildly tuned, fires only when it actually matters
   - `i_noticed` — wildly observant, sees what you didn't say
   - `now_the_moment` — wildly contextual, picks the perfect second
   - `thought_youd_want` — wildly taste-driven, brings only the best

## The five speech acts

Every fired Attention is communicatively a *message Donna chose to interrupt with*. Today's brain conflates five distinct speech acts under one judging shape. Naming them lets each one be calibrated independently.

| Speech act | What she's saying | Posture | Threshold | Register | Failure cost |
|---|---|---|---|---|---|
| `dont_forget` | "you set this up. I'm the keeper." | keeper | LOW (default fire; skip on strong done/moot signal) | brisk, direct, present-tense, <8 words | missed = brand damage; false positive = forgivable |
| `heads_up` | "world moved. your situation changed." | alert | MEDIUM (fire if non-obvious + actionable) | factual, lead with what changed | false positive = noise; false negative = walks into a wall |
| `i_noticed` | "reflecting back. you may not realize." | mirror | HIGH (state-sensitive) | SOFT, question form, no diagnosis | over-fire = surveillance creep; lose trust |
| `now_the_moment` | "the time has arrived for the thing you wanted." | anticipator | MEDIUM-HIGH (confidence the moment IS now) | short, tied to original intent, echo her language | wrong timing = confusing; missed = useless |
| `thought_youd_want` | "this is content. EARN the interrupt." | curator | HIGHEST (default silence) | enthusiast not breathless, one-line gist + URL | each unworthy fire dilutes the channel |

Calibration targets (post-rollout):

- `dont_forget` ~95% fire rate
- `heads_up` ~50-70%
- `i_noticed` ~15-25%
- `now_the_moment` ~60-80%
- `thought_youd_want` ~5-10%

These become the eval suites' acceptance criteria.

## Components

### `ProactiveEvent` envelope (extended)

```python
# proactive/events.py
ProactiveSource = Literal[
    "gmail",
    "attention_fire",
    "attention_offer",
    "calendar",
    "system_b_web",       # NEW — System B as a source
]

SpeechAct = Literal[
    "dont_forget",
    "heads_up",
    "i_noticed",
    "now_the_moment",
    "thought_youd_want",
]

@dataclass(frozen=True)
class ProactiveEvent:
    user_id: str
    source: ProactiveSource
    source_ref: str
    topic_key: str
    speech_act: SpeechAct          # NEW — set at emission
    payload: dict[str, Any]
    signals: dict[str, Any] = field(default_factory=dict)
```

**Speech act is set at the source adapter**, based on what's intrinsic to the event:

| Source | Default speech_act | Notes |
|---|---|---|
| `gmail` | `heads_up` | World produced a message |
| `attention_fire` (origin=USER_REQUESTED, card=PING) | `dont_forget` | User opted in |
| `attention_fire` (origin=DONNA_ANTICIPATED) | `now_the_moment` | Donna decided in advance |
| `attention_fire` (origin=SHADOW_INFERRED, ObservationFrequency) | `i_noticed` | Pattern surfaced |
| `calendar` | `heads_up` | World produced a change |
| `system_b_web` | `thought_youd_want` (default), upgrade to `heads_up` if `signals.is_urgent_signal` | LP-driven curation |

Tier 2 may reclassify via `JudgeResult.reclassify_speech_act` if it disagrees with the source's tag.

### System B fold-in

System B keeps its query gen and execution machinery (`backend/web/proactive/system_b/query_gen.py`, `fetcher.py`, the LP-driven 8-12 query fanout with required dimensional coverage). What changes is what it does *after* fetching: instead of running its own judge + delivery + cap, it emits one `ProactiveEvent` per hit into the unified pipeline.

Per-hit emission in a new `proactive/sources/system_b.py`:

```python
async def emit_hits_for_user(user_id: str, results: list[ProactiveResult]) -> None:
    for result in results:
        for hit in result.hits:
            event = ProactiveEvent(
                user_id=user_id,
                source="system_b_web",
                source_ref=hit.url,
                topic_key=f"sysb:{hit.domain}:{quote_hash(result.move.query)}",
                speech_act=infer_speech_act_from_hit(hit, result.move),
                payload={
                    "url": hit.url,
                    "title": hit.title,
                    "excerpt": hit.excerpt,
                    "domain": hit.domain,
                    "published_at": hit.published_at,
                    "query": result.move.query,
                    "angle": result.move.angle,
                    "ties_to": result.move.ties_to,
                    "render_hint": result.move.render_hint,
                },
                signals={
                    "exa_score": hit.score,
                    "freshness_hours": hit.freshness_hours,
                    "is_urgent_signal": is_urgent_signal(hit, result.move),
                },
            )
            await dispatch(event)
```

What System B keeps: query gen prompt + fanout rules, Exa execution, per-query trace files, cadence tuning (poll = 1h, drain = 10m, url_similar = weekly).

What System B retires (replaced by unified pipeline):

| Today (System B) | After fold-in |
|---|---|
| `backend/web/proactive/judge.py` | `proactive/judge.py` (Tier 2, speech-act-aware) |
| `backend/web/proactive/delivery.py` ship path | Unified ship |
| `DailyCountRepo` cap inside `triggers/drain.py` | Unified arbiter daily cap (single counter for all sources) |
| Per-tick `delivery_mode` parameter | `users.living_profile['proactive_delivery_mode']` |
| `PostgresDedupStore` per-tick | Unified arbiter per-topic dedup (same store) |
| No Tier 3 escape | Can escalate to Tier 3 when judge needs tools |
| Implicit `thought_youd_want` register | Explicit `speech_act` field per emission |

### Tier 2 — speech-act-aware judge-and-author

One Haiku 4.5 call per event. Shared scaffold + per-act block. The `JudgeResult` schema gains two fields:

```python
@dataclass(frozen=True)
class JudgeResult:
    # existing
    action: Literal["ping", "hold", "drop"]
    register: Literal["alert", "soft"] | None
    draft: str | None
    tie_in: list[str]
    needs_tools: bool
    reasoning: str
    raw_response: str

    # NEW
    channel_hint: Literal["whatsapp", "dashboard", "digest", "hold"] | None
    reclassify_speech_act: SpeechAct | None
```

Prompt structure:

```
SYSTEM (cached prefix):
  <Donna voice charter — lowercase, no em dashes, no semicolons, blunt>
  <output JSON schema>
  <skip-as-success principle>

USER (variable):
  <USER MODEL block>      # cached separately, hours TTL
  <TODAY block>
  <RECENT CHAT (last 5 lines)>
  <PROACTIVE EVENT>
    source: ...
    speech_act: ...
    payload: ...
    signals: ...

  <PER-ACT BLOCK — selected by event.speech_act>
    posture: ...
    threshold: ...
    register: ...
    draft conventions: ...
    examples (✓/✗): ...
    when to escalate: ...
    channel guidance: ...

  Decide: ping / hold / drop.
```

The per-act block is the variable part. The shared scaffold (voice, schema, skip-as-success) is a stable prefix and benefits from prompt caching.

Voice validator runs after judge call:
- Strip em dashes, semicolons
- Uppercase ratio check (>5% non-acronym → re-author once with explicit lowercase instruction)
- Emoji flag → re-author once; if still present, escalate to Tier 3
- Failure paths → escalate to Tier 3

### Channel decision (revised — dashboard is ambient, not a channel)

The dashboard is the ambient destination for everything (any `chat_messages` row with `is_proactive=true` shows up via `backend/dashboard/compose.py`). "Pick dashboard as channel" is a non-action — every fire that writes a chat_messages row is already dashboard-visible.

The real decision space collapses to two axes:

```python
@dataclass(frozen=True)
class ShipAction:
    push: bool
    surface_at: Literal["next_user_touch", "morning_brief"] | None = None
```

| `push` | `surface_at` | Effect |
|---|---|---|
| `True` | `None` | WhatsApp ping + chat_messages row |
| `False` | `None` | chat_messages row only — ambient on dashboard, no push |
| `False` | `"next_user_touch"` | chat_messages row + `pending_proactive_notes` row, surfaces when user texts next |
| `False` | `"morning_brief"` | chat_messages row + pending note tagged for next morning brief, batched with siblings |

Tier 2 emits `channel_hint`. Tier 3 calls `send_burst(messages, push, surface_at)` — channel is inline, not a separate tool.

### Tier 3 — fat-contract editorial brain

Triggered by one of six escalation reasons:

1. `needs_tools=true` — Tier 2 flagged it can't decide without checking
2. `action=ping` with empty/malformed draft
3. Voice validator failure that auto-repair can't fix
4. Speech-act stakes-aware (`i_noticed` + mood_low; `heads_up` + urgent + cap-pressure; `reclassify_speech_act` non-null; `dont_forget` for engagement-backed-off recurring item)
5. `action=hold` with channel ambiguity
6. Hard fallback (JSON parse failure / Haiku timeout / 5xx)

Mechanics:

```python
# proactive/dispatcher.py — replaces today's _escalate_to_brain
async def _escalate_to_brain(
    event: ProactiveEvent,
    judge: JudgeResult,
    escalation_reason: EscalationReason,
) -> DispatchOutcome:
    cfg = DonnaAgentConfig(
        mode="proactive_tier3",   # NEW — distinct from reactive's "proactive"
        user_id=event.user_id,
        user_phone=phone,
        stateless_sessions=True,
        max_turns=3,              # vs reactive's 6
    )
    state = {
        "user_id": event.user_id,
        "phone": phone,
        "raw_input": _build_tier3_user_message(event, judge, escalation_reason),
        "trigger": {
            "source": event.source,
            "speech_act": event.speech_act,
            "topic_key": event.topic_key,
            "escalation_reason": escalation_reason,
        },
        "_tier2_proposal": asdict(judge),
        "_event_payload": event.payload,
        "_event_signals": event.signals,
    }
    return await donna_turn(state, cfg)
```

#### Tier 3 input contract — 11 blocks

```
1. WHY YOU'RE AWAKE (2 lines, always)
   escalation_reason, speech_act, source

2. USER MODEL (cached prefix, shared with reactive brain)
   Living Profile: narrative, current_situation, today_shape,
                   active_tensions, what_changed_this_week, key_people,
                   running_themes
   timezone, place, name, quiet_hours_window, engage_window, delivery_mode

3. THE QUEUED THING (full spec, not summary)
   attention_id, title, description, card, subject, domain_tags
   spec.sources[], spec.extractor.prompt, spec.cadence
   spec.surface_policy (default level, urgent_if, escalations, nudge,
                        quiet_hours_respected)
   spec.relevance_threshold, spec.dedup, spec.expires_at
   created_at, last_surfaced_at
   shadow_state {tick_count, promotion_hits}
   user_engagement {accepts, dismisses, mutes, last_*}

4. THE EVENT PAYLOAD (what just triggered)
   source-specific (system_b_web / gmail / attention_fire / calendar)
   topic_key

5. TIER 2's FULL OUTPUT (the hint, not the constraint)
   action, register, draft, tie_in, reasoning,
   needs_tools_reason, reclassify_speech_act, channel_hint

6. DAY VIEW (today, user's tz)
   sent_today, user_messages_today, proactive_fires_today,
   proactive_fires_count_today (vs cap), live_attentions_count,
   open_loops_count, one_line_day_summary (synthesized at context build)

7. PRIOR TOUCHES (last 7 days, dedup against double-tap)
   last_proactive_fire (any topic), last_proactive_fire (this topic_key)
   discussed_in_chat (this topic_key, last 7d): found, last_chat_at,
                                                sample_quote, count
   related_open_loops, related_attentions, related_observations

8. USER STATE NOW (right-this-second read)
   mood_signal, focus_signal, mid_activity, last_message_at,
   message_register, in_quiet_hours, in_engage_window,
   recent_chat_tone (last 30 min synthesis if relevant)

9. PENDING NOTES (active hold-lane state)
   list of (id, topic_key, speech_act, surface_at, age_hours, draft)

10. FRESH SIGNAL (CONDITIONAL — only when speech_act ∈
    {heads_up, now_the_moment} AND event_age > 60min)
    re-fetched_at, result, delta_from_original

11. AVAILABLE TOOLS (system-prompt section)
    send_burst, skip, reshape_attention, kill_attention,
    quick_check, read_external
    Hard constraint: exactly one terminator per turn.
```

What's deliberately excluded: full chat history, calendar >18h ahead, procedural rules, recall fanout, other queued fires, bitemporal facts, subagent outputs.

#### Tier 3 system prompt

```
You are Donna in editorial mode. The queue and Tier 2 already decided
that something is worth your attention. Your job is to execute it
amazingly — or to recognize that the moment is dead and skip cleanly.

You are NOT deciding from scratch whether to ping. The arbiter and
Tier 2 have done that work. Your job is to take what they handed you
and ship the BEST POSSIBLE version of this fire — or, if fresh signal
shows the moment moved, to reshape, kill, or hold.

Default action: ship Tier 2's draft (after one editorial pass).
Skip is a first-class outcome — not a failure. Silence is correct
when fresh signal shows the user already addressed this, the moment
has passed, or your tools reveal redundancy with a recent fire.

Speech act: <event.speech_act>
Apply the speech act's register (see PER-ACT EDITORIAL GUIDE below).

You have 3 turns. Default = use the context. It has DAY view, prior
touches, fresh signal, and Tier 2's read. Most fires don't need
fetches.

WHEN TO USE EACH TOOL
  send_burst         — to ship (specify push + surface_at)
  skip               — to end without sending
  reshape_attention  — when fresh signal shows spec is wrong but useful
  kill_attention     — when fresh signal shows spec is moot
  quick_check        — verify a factual claim, max 1 call per turn
  read_external      — fresh state of a specific external resource

DO NOT:
  - call quick_check or read_external when context is sufficient
  - re-judge whether to fire from scratch (that's Tier 2's job)
  - draft from scratch when Tier 2's draft is usable (polish, don't
    replace)
  - use em dashes, semicolons, capital letters, or emojis
  - end a turn without calling exactly one of:
    {send_burst, skip, reshape_attention, kill_attention}
```

#### Tier 3 tool palette (6 tools)

```python
# donna_runtime/tools_tier3.py

# ─── READS (used sparingly) ──────────────────────────────────────

@tool("quick_check")
async def quick_check(question: str, max_results: int = 3) -> dict:
    """One-shot web search to verify a specific claim or fetch a focused
    fact. Backed by exa_search. Returns title + url + excerpt per hit.
    USE WHEN:    event makes a factual claim that needs verification, OR
                 thought_youd_want needs a freshness check.
    DO NOT USE:  for general research or exploration.
    HARD LIMIT:  one call per turn — second call is a contract violation.
    Cost: ~$0.005, ~1-2s."""

@tool("read_external")
async def read_external(
    source: Literal["gmail_thread", "calendar_event", "exa_url",
                    "person_recent_chat"],
    ref: str,
) -> dict:
    """Fresh state of one specific external resource by identifier.
    Use when fresh_signal block doesn't cover what you need.
    Cost: source-specific, ~0.5-2s."""

# ─── WRITES / TERMINATORS (every turn ends with one) ─────────────

@tool("reshape_attention")
async def reshape_attention(
    attention_id: str,
    next_fire_at: datetime | None = None,
    surface_level: SurfaceLevel | None = None,
    cadence_change: dict | None = None,
) -> dict:
    """Modify the live attention spec without firing.
    USE WHEN:    world changed but spec is still useful (push, downgrade,
                 fold cadence).
    DO NOT USE:  when right action is fire (send_burst) or moot
                 (kill_attention)."""

@tool("kill_attention")
async def kill_attention(attention_id: str, reason: str) -> dict:
    """Terminate. Sets status=killed, cancels future schedule rows.
    USE WHEN:    user did the thing, moment permanently gone, spec was wrong.
    DO NOT USE:  for transient stale (use reshape with next_fire_at)."""

@tool("send_burst")
async def send_burst(
    messages: list[OutboundMessage],
    push: bool = True,
    surface_at: Literal["next_user_touch", "morning_brief"] | None = None,
) -> dict:
    """Ship. push + surface_at = the four-quadrant channel matrix."""

@tool("skip")
async def skip(reason: str) -> dict:
    """Explicit silence. Telemetry records reason. First-class outcome."""
```

Tools NOT available in Tier 3 (denylist):

| Tool | Why excluded |
|---|---|
| `recall`, `smart_recall` | DAY view + input contract has what's needed |
| `list_calendar`, `list_attentions`, `list_observations`, `list_open_loops` | Already in input contract |
| `attend` | Queueing is upstream — Tier 3 doesn't create new attentions |
| `cancel_attention`, `snooze_attention` | Use `kill_attention` / `reshape_attention` |
| `web_search`, `agentic_web_search`, `research` | `quick_check` covers verification |
| `read_gmail_thread` | Use `read_external(source="gmail_thread", ref=...)` |
| `image` | Proactive fires don't generate images mid-decision |
| `connect_integration` | Onboarding doesn't belong in editorial fires |
| External-side-effect actions (auto-reply, book, etc.) | User-in-loop only — reactive brain's job |

#### Tier 3 output

```python
@dataclass(frozen=True)
class Tier3Outcome:
    action: Literal["ship", "reshape", "hold", "kill", "skip"]

    # ship
    channel: Literal["whatsapp", "dashboard", "digest"]
    messages: list[OutboundMessage]

    # reshape
    attention_id: str
    reshape_kwargs: dict

    # hold
    pending_note: str
    surface_at: Literal["next_user_touch", "morning_brief"]

    # kill
    attention_id: str
    kill_reason: str

    # skip
    skip_reason: str
```

The dispatcher routes:
- `ship` → unified ship path
- `reshape` → updates `attentions` row + reschedules `donna_schedule`
- `hold` → writes `pending_proactive_notes`
- `kill` → marks `attentions.status='killed'` + cancels schedule rows
- `skip` → ends turn, marks fired in worker (no error)

## Migration plan

Five phases. Mirror mode is the discipline through cutover. No phase changes user-visible behavior without a previous phase's exit criterion met.

### Phase 1 — Skeletons (mirror-only, no behavior change)

```
✓ Add `speech_act` field to ProactiveEvent envelope (proactive/events.py)
✓ Source adapters set speech_act at emission
✓ Add `channel_hint`, `reclassify_speech_act` to JudgeResult schema
✓ Build Tier 3 fat-contract input builder
  donna_runtime/context_builder.build_tier3_context (NEW)
✓ Build Tier 3 system prompt
  donna_runtime/prompt.py — new "proactive_tier3" mode branch
  Lower max_turns (3), narrow tool registration
✓ Build Tier 3 tool palette
  donna_runtime/tools_tier3.py (NEW): quick_check, read_external,
  reshape_attention, kill_attention, send_burst (with push/surface_at),
  skip
✓ Build per-source fresh_signal fetchers (conditional pre-fetch)
✓ Mirror-mode logging: every Tier 3 path logs counterfactual
  (both old thin-directive AND new fat-contract). Compare verdicts
  in proactive_dispatch_telemetry.
```

**Exit:** one week on dogfood, fat-contract Tier 3 ships zero messages but logs every counterfactual. Eval shows fat-contract drafts at-or-better than thin-directive in Δ-ratings.

### Phase 2 — System B fold-in (mirror)

```
✓ Build proactive/sources/system_b.py source adapter
✓ Wire system_b adapter into proactive/dispatcher.dispatch
  In mirror: dispatcher logs counterfactual; System B's existing
  judge+deliver still ships
✓ Migrate daily cap counter ownership to unified arbiter
  DailyCountRepo stays; arbiter reads/bumps for ALL sources
✓ Migrate dedup ledger; topic-key conventions unified per-source
✓ Migrate delivery_mode source-of-truth to
  users.living_profile['proactive_delivery_mode']
✓ Build voice validator + reauthor logic for System B's draft path
```

**Exit:** one week on dogfood, unified pipeline + System B ship the *same* messages. Verdict mismatch <5% (logged for review).

### Phase 3 — Speech-act-aware Tier 2

```
✓ Build proactive/prompts/tier2_scaffold.py
  Shared base + per-act blocks (5)
✓ Update proactive/judge.py to compose prompt by event.speech_act
✓ Build per-act eval suites
  ≥50 ground-truth-labeled events per act (fire / hold / drop)
  Run on every commit touching prompts; gate merges on suite pass
✓ Calibrate fire-rate targets per act
  dont_forget ~95% / heads_up ~50-70% / i_noticed ~15-25% /
  now_the_moment ~60-80% / thought_youd_want ~5-10%
```

**Exit:** all five eval suites passing at target ratios within ±10%. Voice validator pass-rate >95% per act.

### Phase 4 — Cutover (gated rollout)

Prerequisites:
```
✓ Cooldown table backfill complete (per CLAUDE.md prerequisite)
✓ Phases 1-3 exit criteria all met on dogfood
✓ Tier 3 cost telemetry shows expected ratios:
  ~80% Tier 2 ships clean, ~10% holds, ~10% Tier 3 escalates
✓ Backout plan documented and tested
  (re-set DONNA_PROACTIVE_TIERED=0 restores legacy behavior in 30s)
```

Cutover:
```
1. Flip DONNA_PROACTIVE_TIERED=1 on dogfood account ONLY
   Per-user override via users.living_profile['proactive_pipeline_version']
2. Watch for 48h: judge-mismatch, draft quality, fire counts
3. Roll to early-access cohort (5-10 users on live mode)
   1 week soak
4. Roll to all live-mode users
5. Roll to shadow-mode users
6. Sunset legacy paths (Phase 5)
```

Halt and investigate if any phase shows >2× judge-mismatch from baseline.

### Phase 5 — Sunset

After tiered is stable across all users for 2 weeks:

```
✓ Remove backend/web/proactive/judge.py
✓ Remove backend/web/proactive/delivery.py shipping path
  (keep deliver_drafts as thin pass-through during transition;
  remove after tiered stable for 4 weeks)
  CARRY-OVER: the auto-URL-append behavior (delivery.py:_ensure_url_in_draft)
  must be preserved in the unified ship path before delivery.py is removed
  — applies whenever speech_act="thought_youd_want" and payload.url is set
✓ Remove donna/attention/firing.py:build_fire_prompt and
  fire_attention_via_brain mirror-mode fallback
✓ Remove proactive/dispatcher.py:_build_escalation_prompt thin shape
✓ Remove DONNA_PROACTIVE_TIERED env var entirely (tiered = default)
✓ Remove backend/web/proactive/triggers/drain.py daily-cap logic
  (now in unified arbiter)
✓ Update CLAUDE.md to reflect new shape (mirror mode is gone)
```

## Cost shape

| Path | Calls | Approx cost |
|---|---|---|
| Tier 2 ships clean (~80%) | 1× Haiku | ~$0.002 |
| Tier 2 holds (~10%) | 1× Haiku + DB write | ~$0.002 |
| Tier 3 with no fetches (~70% of escalations) | 1× Haiku + 1× Sonnet (1 turn) | ~$0.03 |
| Tier 3 with 1 fetch (~25%) | 1× Haiku + 1× Sonnet (2 turns) + 1 fetch | ~$0.05 |
| Tier 3 with max fetches (~5%) | 1× Haiku + 1× Sonnet (3 turns) + 2 fetches | ~$0.08 |
| **Per-fire weighted average** | | **~$0.005** |

vs today (mirror mode, every fire pays full Sonnet 4.6 reactive turn): ~$0.05-0.10 per fire. **~10× reduction** at steady state.

Per-user/day at plausible volume (10-20 events/day):
- Today: $0.50-2.00
- After: $0.05-0.20

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Tier 3 fat-contract slower than thin-directive (more tokens, more tools) | max_turns=3; harness forces `skip(reason="max_turns_exceeded")` if turn 3 doesn't end with a terminator; budget alerts at $0.20/fire |
| Speech-act inference at source emission is wrong | Tier 2 has `reclassify_speech_act`; mismatches logged; iteratively tune source adapters |
| Daily cap unification undercount (race conditions on bump) | Bump-then-mark pattern (today's System B uses this); tolerate slight overcount |
| `quick_check` / `read_external` fail at scale (rate limits) | Each tool has timeout + fallback; system prompt explicitly tolerates "tool returned error" |
| Prompts drift across phases | Eval suite is the gate; can't merge without passing all five suites at calibrated ratios |
| Sunset reveals coupling we missed | Keep mirror-mode logging through Phase 5 (read-only telemetry) for one week post-sunset |
| Voice validator over-rejects (too many escalations to Tier 3) | Track validator pass-rate per act; if <90%, tune scaffold not threshold |
| Tier 3 over-uses `quick_check` | Per-turn hard limit (1 call); telemetry on "calls per fire" — anomaly if >1.5 avg |

## Observability

New tables / metrics:

```
- proactive_dispatch_telemetry (table)
  Every event: source, speech_act, tier1_score, arbiter_decision,
  tier2_action, tier2_draft, tier3_invoked, tier3_outcome, channel,
  user_response_within_1h
- per-act fire-rate dashboards (live vs eval target)
- judge-mismatch rate (System B judge vs unified Tier 2, during Phase 2)
- tier3-cost-per-fire (rolling 7d)
- voice-validator pass-rate per act
- channel-distribution (push / ambient / hold / digest)
- escalation-reason distribution
- tier3-fetch-tool usage (per-fire count, anomaly threshold)
```

Per-user telemetry alert: if a user receives >2× their cap in any 24h window, page on-call.

## Out of scope (deliberate)

- Dashboard recompose-on-ambient-fire (deferred — separate spec)
- Voice channel
- Cross-user pattern noticer
- Active push of OFFERED attentions (tracked in 2026-04-26 spec)
- Bitemporal facts wiring
- Reactive brain's tool palette changes
- New external surfaces (voice, email, calendar invites as outbound)
- External-side-effect Tier 3 actions (auto-reply, book, Composio actions)

## What this gives us

The reframe from your design intent: **what makes attention amazing is that it auto-queues and at the time of sending, the model that takes care of it is perfect for the task.**

Auto-queues → unchanged from today's queueing layer (BRAIN tool, post-turn hooks, proposers, sensors, brain anticipation via `attend(origin='donna')`).

The model that takes care of it is perfect for the task → the new Tier 2 + Tier 3 contract:
1. Speech act is a first-class field, set at emission, biases prompt template through every tier
2. Tier 2 has five distinct postures, calibrated to act-specific fire rates
3. Tier 3 is fat-contract editorial, narrow tool palette, "ship Tier 2's draft after one editorial pass" as default
4. System B is one source among many, no longer parallel
5. Daily cap, dedup, voice validator, delivery mode all unified
6. Mirror mode retires through gated rollout

The proactive surface stops being "everything pays Sonnet cost; thin directive guarantees breakage" and becomes "Haiku does the common case fast and well; Sonnet handles editorial judgment with a real input contract." That's the architecture the user described as "the model that takes care of it is perfect for the task."
