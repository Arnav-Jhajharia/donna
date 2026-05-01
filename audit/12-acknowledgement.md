# 12 — Acknowledgement while sending

The "drawing this, one sec" pattern: when Donna runs an expensive thing, she should let the user know something is happening so they don't stare at silence.

## What's there

Two ack mechanisms exist:

1. **Image ack.** `donna_runtime/hooks.py:322-362`. Constants `_IMAGE_ACK_TEXT = "drawing this, one sec"` and `_IMAGE_ACK_EMOJI = "🎨"`. Fires inside `pre_tool_hook` when the model calls `image` (`hooks.py:222`). It dispatches a fire-and-forget task that does two things in parallel: a WhatsApp emoji reaction on the inbound user message, and a text message saying "drawing this, one sec".
2. **Typing indicator on inbound.** `delivery/whatsapp.py:167-182` — `WhatsAppChannel.send_typing` posts `mark_as_read + typing_indicator` to the WA Cloud API. It's called once per inbound at `api/main.py:613` (`asyncio.create_task(_wa.send_typing(payload.phone, wa_id))`) the moment the webhook arrives, before `_dispatch` runs the brain.

Reaction support: `WhatsAppChannel.send_reaction` (`delivery/whatsapp.py:145`) posts an emoji reaction on a specific message id. Used only by the image ack.

## What works

- **Inbound typing indicator fires reliably.** Every WhatsApp inbound triggers `send_typing` from `api/main.py:610-613`. Best-effort, fire-and-forget, so a slow WA doesn't stall the webhook ack. The typing dots show in WhatsApp the moment the brain starts.
- **Image ack fires before the image tool runs.** Pre-tool hook order is: cap check → fire ack. By the time fal.ai is generating (12-30 seconds), the user has already seen a 🎨 reaction on their own message and a "drawing this, one sec" text bubble. That's an actual ack with voice.
- **Fail-soft.** Both `send_typing` and `send_reaction` log warnings and never raise. The image ack is wrapped in try/except and skips silently when phone or message_id are missing (CLI runs, post-call brain, proactive triggers without a message id).
- **Voice register.** `_IMAGE_ACK_TEXT = "drawing this, one sec"` is lowercase, no punctuation, no em dash, terse. That sounds like Donna.

## What's broken or missing

- **Only `image` has an ack hook.** Search confirms `_fire_image_ack` is the only ack fire. There is no equivalent for:
  - `research` (deep research, multi-step, often 20-60 seconds).
  - `agentic_web_search` (Exa-backed, can take 10+ seconds).
  - `web_search` (usually fast but variable).
  - `read_gmail_thread` when it has to lazy-fetch a body from Composio.
  - `compile_brief`, `dig_deeper`, `draft_high_stakes_message` — the subagent tools mentioned in CLAUDE.md (none of which exist in the current `tools.py`, but the principle would apply).
  - Voice synth. `voice_synth.maybe_synthesize_voice` runs inside `send_burst`, blocking the burst. ElevenLabs synthesis can take 2-5 seconds and there is no "recording, one sec" ack.
- **Typing indicator only fires once.** It's posted at webhook intake. WhatsApp typing dots auto-expire after ~25 seconds. A research turn that runs 40 seconds gets a dead-air gap before the burst lands. There's no re-poke.
- **No teaser/placeholder pattern.** Nothing sends an interim message like "looking into this, one sec" before a long tool chain. The image ack is the only example, and it's tool-specific rather than a general "this is going to take a while" signal.
- **Ack is silently dropped on CLI.** `_fire_image_ack` returns early when `trace.user_phone` is missing, which is correct behavior — but it means evals and smoke tests cannot catch ack regressions.
- **Idempotency.** Nothing prevents the image ack from firing twice if the model retries `image` in the same turn (it can't, because `image` is rate-capped, but the hook itself has no guard).
- **Reaction drift.** The 🎨 emoji is hardcoded. Voice synth, deep research, etc., would each want their own gesture if the pattern were generalized.

## Opinion — does this match Donna?

The image ack is genuinely well-done. Lowercase, terse, exactly the right shape — "drawing this, one sec" is what a sharp friend would say. The reaction-plus-text combo is a nice touch: the reaction lands instantly on the user's own message, the text bubble follows. That's a real user-facing acknowledgement, not a typing dot.

But the rest of Donna's slow tools have nothing. CLAUDE.md says she's a thinking partner with persistent memory. A thinking partner who goes silent for 40 seconds on a research call feels broken. The system prompt explicitly bans her from saying "let me check" or "one sec" in text — which is correct for short turns, but means there's no fallback when the actual computation is going to be long. The brain has no way to know "this turn will take 30 seconds, send a teaser."

This is the place where the "feel" of Donna leaks. Image acks tell the user she's working. Everything else trusts that the SDK is fast. When it isn't, the user sees a typing indicator that died ten seconds ago and then a burst out of nowhere.

## Verdict

- **Architecture: image-only.** The ack pattern exists, is well-wired, and respects voice. But it's a one-off, not a general mechanism.
- **Production: image works, nothing else does.** Typing indicator covers fast turns. Long turns (research, deep recall, voice synth) have a dead-air problem.
- **Gap to vision: medium.** Donna should ack any tool whose typical latency exceeds ~5 seconds. The mechanism is already proven (`_fire_image_ack`). What's needed is a tool-attribute (`slow_tool: True`) plus a registry of voice-correct ack lines, not new infrastructure.
