# `surprise` tool — spec (pre-code)

status: draft, not yet implemented. description-first per CLAUDE.md. ship order and engagement rationale at bottom.

---

## tool header

**name:** `surprise`

**agency levels (per payload kind):**
- **L0 (auto-fire):** `callback_drop`, `small_win_noticed`, `pattern_spotted`, `inside_joke_recall`
- **L1 (dashboard preview → send on confirm):** `polaroid_artifact`, `seasonal_wrap`, `mini_dossier`, `year_ago_today`
- **L2 (explicit user opt-in per-artifact):** `draft_they_needed`, `quiet_gift`, `curated_find`, `tomorrow_tease`

**render target:** WhatsApp burst (most kinds) + dashboard insight card (all kinds, for legibility). `polaroid_artifact` renders as image+caption. `seasonal_wrap` renders as dashboard card with WhatsApp teaser.

---

## when to use

- after a reactive turn closes, when exactly one trigger condition below is met AND global caps allow AND quiet hours permit.
- as a proactive terminator fired by a scheduled hook (daily 9am scan, milestone hook, anniversary hook, sentiment-dip hook).
- to close an `open_loops` entry tagged "deliver: surprise".
- when the user explicitly asks "surprise me" or equivalent — in that case bypass weekly cap but still honor sentiment gates.

## when NOT to use

- user is mid-crisis (sentiment < -0.6 in last turn, or self-harm/distress markers).
- quiet hours active per Living Profile.
- weekly cap (3 total) or per-kind cap already hit.
- the triggering memory is tagged grief / breakup / job-loss / medical-bad-news.
- no real retrieval match — never fabricate a callback. if the memory isn't there, don't fire.
- open loop from a prior `tomorrow_tease` is still unfulfilled.
- user has asked for space in the last 24h.
- as a reply to a direct task request — surprise is additive, never a substitute for doing the thing asked.

---

## payload catalog

| # | kind | trigger | payload | cap | agency | render |
|---|------|---------|---------|-----|--------|--------|
| 1 | `callback_drop` | semantic match to episodic memory >14d old, salience ≥0.6 | one-liner quoting past self | 2/wk | L0 | whatsapp |
| 2 | `pattern_spotted` | entity mentioned ≥3x across ≥7d | "you've brought up your sister four times this month" | 1/wk | L0 | whatsapp + card |
| 3 | `tomorrow_tease` | overnight artifact queued | "got something for you in the morning. sleep." | 1/wk, **must deliver ≤18h** | L2 | whatsapp |
| 4 | `mini_dossier` | new interest mentioned ≥2x | 4-bullet brief from docs+web | 2/mo | L1 | card + whatsapp summary |
| 5 | `polaroid_artifact` | open loop tagged milestone closes | generated polaroid + one-line caption | 2/mo hard cap | L1 | image |
| 6 | `curated_find` | high-signal match to stated interest | single link + one sentence why | 1/wk | L2 | whatsapp |
| 7 | `draft_they_needed` | "hard conversation" open loop >72h unresolved | drafted message to send as-is or edit | on-trigger | L2 | whatsapp |
| 8 | `year_ago_today` | anniversary entry, sentiment ≥+0.4 **only** | "a year ago today you wrote X. where are you now?" | 1/mo | L1 | whatsapp |
| 9 | `small_win_noticed` | observation log: user followed through on stated intention | "you said monday you'd call your dad. you did. noting." | 2/wk | L0 | whatsapp |
| 10 | `quiet_gift` | sentiment <−0.4 in last 24h AND now idle | one low-effort useful thing: playlist, 3-min read, past win | 1/wk, suppressed if user asked for space | L2 | whatsapp |
| 11 | `seasonal_wrap` | end of month/quarter | 3 bullets: theme, pattern, open loop | monthly | L1 | card + whatsapp teaser |
| 12 | `inside_joke_recall` | prior exchange hand-tagged funny | one-line callback at an apt moment | 1/wk, never forced | L0 | whatsapp |

---

## input schema

```python
{
  "kind": Literal[
    "callback_drop", "pattern_spotted", "tomorrow_tease", "mini_dossier",
    "polaroid_artifact", "curated_find", "draft_they_needed", "year_ago_today",
    "small_win_noticed", "quiet_gift", "seasonal_wrap", "inside_joke_recall"
  ],
  "trigger_evidence": {
    "memory_ids": list[str],       # required. must be non-empty. anchors the payload to real retrieval.
    "salience": float,             # 0.0 - 1.0
    "sentiment": float,            # -1.0 - 1.0
    "entities": list[str],
    "rationale": str,              # one sentence, internal. why this kind, this moment.
  },
  "payload": {
    "text": str,                   # message copy in her voice. lowercase. no em dashes. no filler.
    "artifact_spec": Optional[{    # only for kinds that generate media
      "type": Literal["polaroid", "dossier_card", "wrap_card"],
      "prompt": str,
      "caption": str,
    }],
    "attachment_url": Optional[str],  # curated_find
    "draft_message": Optional[str],   # draft_they_needed
  },
  "cap_check": {
    "weekly_count": int,           # must be < 3
    "daily_count": int,            # must be < 1
    "per_kind_remaining": int,     # must be > 0
  }
}
```

## output

```python
{
  "sent": bool,
  "channel": Literal["whatsapp", "dashboard", "both"],
  "suppressed_reason": Optional[str],  # populated if PreToolUse hook blocked
  "logged_to": list[str],              # e.g. ["chat_messages", "insight_cards", "open_loops.close"]
}
```

---

## global caps

- ≤3 proactive surprises per week total, hard ceiling 1/day.
- honor quiet hours from Living Profile.
- suppress during detected anxiety state (sentiment + stress markers).
- industry push-notification fatigue threshold ~3/wk for generic pings; personalized high-signal surprises tolerate slightly more but donna's voice punishes noise fast.

## PreToolUse guards (hooks.py)

1. quiet hours check (Living Profile).
2. weekly/daily cap counter.
3. sentiment gate: reject if last-24h sentiment < -0.6 OR triggering entity has negative-affect tag.
4. fabrication guard: reject if `trigger_evidence.memory_ids` is empty.
5. open-loop debt check: reject if an unfulfilled `tomorrow_tease` exists.
6. SB 243 disclosure: if kind is `quiet_gift` or `draft_they_needed` and user is <18, inject AI-identity reminder.

## PostToolUse side effects

1. log to `chat_messages` + `insight_cards`.
2. increment cap counters.
3. if `tomorrow_tease`, write an `open_loops` row with `deliver_by` ≤ 18h.
4. if `polaroid_artifact` or closes a milestone, write `living_profile.milestones`.
5. observation: record whether user replied within 6h (for future bandit tuning).

---

## failure modes to design against

- caps bypassed by re-firing different kinds back-to-back → global count, not per-kind count.
- fabricated callbacks → `memory_ids` required + PostToolUse audit that IDs resolve.
- positivity-only filter turning donna saccharine → `small_win_noticed` and `pattern_spotted` can be neutral or wry, not just praise.
- surprise arriving during real distress → sentiment gate + hard suppress on crisis markers.

## evals before ship

- reply-rate by kind (target: >40% within 6h).
- user "stop" / "quiet" response rate (target: <2%).
- fabrication audit (target: 0% — every `memory_ids` resolves).
- cap-violation rate (target: 0%).
- false-positive rate on sentiment gate (manual review n=20 per week for first month).

---

## ship order

1. `callback_drop` → `small_win_noticed` → `pattern_spotted`. all L0, all lean on existing memory, lowest risk.
2. `seasonal_wrap` + `year_ago_today`. L1, require dashboard preview flow.
3. `tomorrow_tease` + `quiet_gift` + `draft_they_needed`. L2, require user opt-in UX.
4. `polaroid_artifact` + `mini_dossier` + `curated_find` + `inside_joke_recall`. last — require artifact generation pipeline or manual tagging.

## engagement rationale (short)

one loop: **zeigarnik open loop → tiny fogg-sized prompt → variable but earned reward → living-profile investment → peak-engineered ending → parasocial continuity via memory callbacks.**

surprise is the "variable but earned reward" step. variance lives in which kind fires when, not in whether the payload is worth reading. never slot-machine. every firing must be something the user would pay for if they knew it was coming.

## anti-patterns (do not ship)

- no streak counter. no guilt mechanic.
- no variable-ratio slot randomization.
- no unfiltered nostalgia (sentiment-gate anniversaries).
- no performative empathy in payload copy.
- no manufactured dependency ("donna misses you").
- no bereal-style panic windows.
- SB 243 compliance by default.

---

## research sources

full cited research brief in conversation history. key citations:
- Zeigarnik effect — open loops drive return
- Schultz 1998 — reward prediction error, anticipation > receipt
- Kahneman peak-end rule + 2022 OBHDP meta-analysis
- Fogg B=MAP behavior model
- Eyal Hooked model (trigger/action/variable reward/investment)
- Nunes & Drèze endowed progress
- Norton/Mochon/Ariely IKEA effect
- Duolingo streak leniency findings (use forgiveness half only)
- Spotify Wrapped psychology (Growth.design, Decision Lab)
- Google Photos sentiment-gated Memories lesson
- FTC 6(b) inquiry Sept 2025 + CA SB 243 (compliance floor)
- Replika TJLP complaint Jan 2025 (dark-pattern boundary)
