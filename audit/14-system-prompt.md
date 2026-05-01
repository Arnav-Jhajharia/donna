# 14 — System prompt quality + situational awareness use

The brain prompt is two pieces glued together:
1. A **stable system prompt** that every turn reuses (so the prefix cache stays warm).
2. A **per-turn wrapped user message** that prepends user-specific data to whatever the user said.

## What's there

### The stable system prompt — `donna_runtime/prompt.py`

`_DONNA_CORE` (`prompt.py:31-232`) is a single 200-line block with section headers:
- **IDENTITY** — "You are Donna. You work for one person. She/her."
- **VOICE** — lowercase, no em dashes, no semicolons, no emojis, no markdown, no "let me check."
- **TASTE** — sharp, specific, not customer-support, no flattery.
- **MISSION** — reduce cognitive load, hold threads, surface next moves.
- **MODALITY** — when to use voice, when to stay text.
- **AGENCY** — high-agency default, when to ask vs act.
- **CAPTURING CONCRETE FUTURE COMMITMENTS** — `attend` vs `track_open_loop` distinction, with multiple voice examples ("i have a midterm tomorrow at 11am" → call `attend` twice, do not ask).
- **WORKING MEMORY** — what to do with USER MODEL, LIVING PROFILE, TODAY, RECENT CHAT, ATTENTIONS WAITING.
- **SITUATIONAL AWARENESS** — "You are reading a person, not routing tools." Two reactive-with-proactive examples.
- **SYNTHESIS** — "Tools gather. They do not answer. A tool result is raw material, not a reply."
- **AFTER PRIVATE ACTIONS** — don't sound like a receipt.
- **WHATSAPP IS THE INTERFACE** — image use rules.
- **TOOLS / INTEGRATIONS / FIRST MESSAGE / SAFETY FLOORS.**

Then `_TERMINATOR_CONTRACT` (`prompt.py:235`) appends `_WHATSAPP_CAPABILITIES` (the burst widget guide imported from `delivery/whatsapp.py:42`).

`build_system_prompt` (`prompt.py:268-282`) returns `STAGE_0_5_PROMPT` for the real/fake tool modes — same text every turn. **Per-user data deliberately does NOT live here.**

### The per-turn wrapped user message — `prompt.wrap_user_message_with_context` + `context_builder.render_turn_context`

`brain.donna_turn:55-58` builds:
```
system_context = cfg.system_context + render_turn_context(state)
user_model_block = await load_user_model_block(user_id)
```
Then `runner._donna_turn_core:92-96` calls `wrap_user_message_with_context(user_message, system_context, user_model_block)`, producing:
```
## USER MODEL
[Living Profile + Situation Brief, from backend.memory.user_facts.rendering.load_and_render]

## Runtime Context
user_id, name, timezone, local_time, first_message
[VOICE REQUEST DETECTED] (when applicable)
[TIMEZONE CHECK] (when unconfirmed)
[REPLY CONTEXT]
[URL CONTEXT]
[## TODAY] (next 24h calendar, today's observations, open loops, attentions)
[## ATTENTIONS WAITING]
[## PENDING NOTES]
[## INTEGRATIONS]
[RECENT CHAT (last N messages)]

## USER MESSAGE
[the actual inbound]
```

### LP rendering — `backend/memory/user_facts/rendering.py:load_and_render`

CLAUDE.md says LP is rendered into the system prompt by `load_and_render`. It actually goes into the **wrapped user prompt** (`context_builder.load_user_model_block:70-84`), not the system prompt. `prompt.load_living_profile` exists (`prompt.py:12-28`) but the comment says "Kept for compatibility; not used by the current prompt." Production reads happen via `load_user_model_block`.

## What works

- **Voice rules are dense and specific.** "Lowercase. No em dashes, no semicolons, no emojis, no markdown" is in the prompt and enforced by a runtime filter (`tool_logic.set_voice_filter_enabled`). Belt and suspenders.
- **Cache discipline is real.** System prompt is byte-stable across users and turns. Per-user data is in the wrapped user message. `cache_ttl_1h=True` extends the cache window. `extra_args` disables built-in tools and dynamic system-prompt sections so the prefix doesn't drift.
- **Tool descriptions all carry when-NOT-to-use.** Spot-check: `recall` (`tools.py:931`), `remember` (`tools.py:1017`), `read_tracker` (`tools.py:118`), `recall_graph` (`tools.py:142`), `web_search` (`tools.py:1347`), `agentic_web_search` (`tools.py:1421`), `composio_search_tools` (`tools.py:319`), `list_calendar` (`tools.py:216`). Every tool has multiple "Do NOT use" clauses. This is the CLAUDE.md non-negotiable being followed.
- **Situational awareness is loaded right.** The TODAY block is built fresh each turn from real DB rows (`context_builder._fetch_today_sections`), and capped: 6 calendar items, 8 observations, 6 open loops, 5 attentions. Filtered through `donna.attention.noise.filter_attentions` to drop debug tokens. INTEGRATIONS block is reconciled with Composio at most every 120s with a 1.5s timeout.
- **First message detection.** `first_message: True` in runtime context triggers a hard rule: call `send_dashboard_link(reason="first_message")` before `send_burst`. Wired in the prompt at "FIRST MESSAGE + DASHBOARD ACCESS."
- **Voice-request injection.** When `_detect_voice_request(state)` returns true, the runtime context hardcodes "VOICE REQUEST DETECTED" with explicit instructions. Belt-and-suspenders: `pre_tool_hook._maybe_inject_voice_response` (`hooks.py:277`) injects the marker if the model emitted text-only.
- **Timezone unconfirmed flag.** `_tz_done == False` injects a TIMEZONE CHECK block telling the model to ask for confirmation and call `remember` with the IANA name. Self-healing once the user replies.

## What's broken or missing

- **`build_system_prompt` has dead parameters.** It accepts `living_profile`, `runtime_context`, `user_model_block`, then `del`s all three (`prompt.py:280`). Kept for backward-compat with old callers; safe but confusing.
- **`prompt.load_living_profile` is dead code.** Self-documented as "not used by the current prompt." Production path is `context_builder.load_user_model_block`.
- **Two `donna_turn` signatures.** `runner.donna_turn` takes a `(message, config)` pair; `brain.donna_turn` takes `(state, config)`. Different worlds, same name.
- **The "WORKING MEMORY" block in the system prompt is opinionated but the actual rendered context can drift.** Example: the prompt says "RECENT CHAT entries are timestamped `[YYYY-MM-DD HH:MM] role: text`" — `context_builder._format_recent_chat_line:777` does emit that exact format. Good. But the section "ATTENTIONS WAITING" is described in detail, and the rendered block (`context_builder.render_offered_attentions_block:358`) only fires if there are offered attentions — model is told a block exists that may not. Minor.
- **Prompt bloat.** `_DONNA_CORE` is roughly 200 lines, ~12k chars. The CAPTURING CONCRETE FUTURE COMMITMENTS section alone has three voice examples that take 25 lines. They're well-written but could be one example. Cache covers most of the cost, but token-cost on cache miss (post 1h) is real.
- **Multiple competing "what to do when LP says X" instructions.** The prompt now says: read LP as ambient knowing, don't quote it, don't announce it, but also "if their tone or rhythm is off versus the LIVING PROFILE — flatter, snappier, quieter, awake when they should be asleep — read it as signal." Combined with the CLAUDE.md note that LP is loaded once at start of turn and not refreshed mid-turn, this is functionally one rule but reads as overlapping rules.
- **No explicit max-token discipline in the prompt.** The system prompt says "Tool count goes up, word count goes down" and "burst is ≤3 items" — both are voice rules, not token rules. The schema enforces 6, prompt says 3, CLAUDE.md says low single-digit cents per turn — those are three separate dials.
- **Stage 0 and 0.5 prompts diverge.** `STAGE_0_PROMPT` says "You have no memory tools" (`prompt.py:248-252`); `STAGE_0_5_PROMPT` says "Memory and action tools are available." Production runs Stage 0.5. Stage 0 is dead path (used by `tool_mode == "stage0"`). One more dead branch.

## Opinion — does this match Donna?

The prompt is genuinely good. It reads like someone wrote it on purpose, in voice. "Tease the situation, not the user." "She does not customer-support." "Tools gather. They do not answer." "Wit comes from the read, not from performing." Those are not generic agent-prompt lines — they're a personality. The reactive-with-proactive examples ("yo what time's my call with maya" → check calendar + read LP + suggest "eat first, you've been running on fumes") are exactly the kind of move a sharp human assistant would make.

The wrapped user message is doing real work. USER MODEL renders the Living Profile from backend.memory rendering, which is the nightly synthesis MEMORY.md flags as the thing that should drive Donna's smarts. TODAY is a DB-truth snapshot. RECENT CHAT is timestamped so the model can read the rhythm. ATTENTIONS WAITING and PENDING NOTES are state surfaces that carry continuity.

But: the prompt is asking the model to do the synthesis. Whether the model actually leverages the LP for tool selection, or just reads it as flavor text, is a question of trace data, not prompt text. The system prompt explicitly says "do not quote LP back, do not announce it" — which is the right answer, but means the only signal that LP worked is whether the right tool got called and the right voice came out.

The voice rules are the strongest part. The runtime voice filter (`tool_logic._VOICE_FILTER_ENABLED`) catches em dashes and semicolons even when the model slips. That's the kind of belt-and-suspenders that makes the persona robust.

What feels off: the prompt is long. Cache mitigates the cost on warm turns, but a 12k-char system prompt + 3.6k-char-capped wrapped context means every cold turn is paying for all those examples. And there's no signal in the trace that any of the situational awareness blocks (LP narrative, ATTENTIONS WAITING, PENDING NOTES) actually changed the model's behavior on a given turn versus would have been a no-op. The prompt promises "ambient knowing" — the only way to verify is to run paired evals with and without each block. Those don't exist (or aren't visible in this audit).

## Verdict

- **Architecture: opinionated and right.** Stable system prompt + per-turn wrapped context, cache-warm by design, voice rules belt-and-suspendered with a runtime filter, every tool description carries when-NOT-to-use.
- **Production: voice and situational awareness are wired.** LP, TODAY, RECENT CHAT, attentions, integrations all render per turn from real DB rows. First-message + voice-request + timezone-unconfirmed paths all self-heal.
- **Gap to vision: low. Mostly drift.** Drop the dead `load_living_profile` and dead `build_system_prompt` parameters. Trim or rotate the CAPTURING examples. Decide whether Stage 0 is alive. Wire eval data that confirms LP actually changes behavior — without that, "ambient knowing" is faith.
