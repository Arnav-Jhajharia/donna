# 13 — send_burst division

`send_burst` is the only way Donna ends a turn. Its argument is a list of items that render as a sequence of WhatsApp messages with optional pacing.

## What's there

- **Tool definition.** `donna_runtime/tools.py:2474-2502`. Description literally says "TERMINATOR — the ONLY way to end a turn. Exactly one send_burst per turn, never twice, no silent exit."
- **Schema.** `SEND_BURST_INPUT_SCHEMA` (`tools.py:1593`). `messages: array, minItems=1, maxItems=6`. Each item is a discriminated union on `type`.
- **Item types** (`tool_logic.py:104-201`, `_build_outbound`):
  - `text` — body up to 1000 chars, optional `reply_to_message_id`.
  - `cta` — body + 1-3 buttons (id+title, title ≤20 chars).
  - `cta_url` — body + display_text + url.
  - `list` — body + button_label + sections (rows ≤24 chars).
  - `image` — `media_id` or `url`, optional caption.
  - `delay` — `seconds: 0.5–4.0`, clamped to 0–10 defensively.
  - `voice_response` — sentinel marker, must be first; concatenates following text bodies into one synthesized voice note.
- **Renderer.** `tool_logic.send_burst_result` (`tool_logic.py:270-293`). Filters via `voice_filter`, builds `OutboundMessage` objects, extends the contextvar `_OUTBOUND_BUFFER`.
- **Plain-text variants.** `render_burst_items_text` (`tool_logic.py:232`) flattens raw schema items into strings for memory hooks. `render_outbound_text` (`tool_logic.py:204`) flattens constructed messages for chat persistence.
- **Delay handling.** `delivery/whatsapp.py:130-143` — `send_many` walks the list, calls `asyncio.sleep(message.seconds)` on each `Delay`, posts everything else.
- **Voice synth.** `send_burst` calls `voice_synth.maybe_synthesize_voice()` after `send_burst_result` (`tools.py:2499-2500`). When a `VoiceResponseMarker` is present, the buffer is mutated in-place: text bodies are concatenated, ElevenLabs synthesizes, the buffer is rewritten as `[delays..., AudioMessage]`.

## What works

- **One terminator, enforced.** `pre_tool_hook` (`hooks.py:192`) blocks any second call to a terminator-suffix tool with `permissionDecision: "deny"`. The trace records the deny event for evals.
- **Empty-burst fallback.** `_build_outbound` returns `None` for empty/invalid items. If every item is filtered out, `send_burst_result` still records `_OUTBOUND_BUFFER` (empty); the top-level `brain.donna_turn` sees an empty `_outbound` and the WA pipeline simply sends nothing. No crash, but also no user-visible reply.
- **Plain-text safety net.** When the model exits without calling the terminator, `runner._fallback_plain_text_to_send_burst` (`runner.py:144`) builds a synthetic `send_burst` from `trace.result_text`, records it as `mcp__donna__send_burst` in the trace with `fallback: "plain_result_text"`, and fires memory hooks. Production users always get a message.
- **Voice filter.** `_VOICE_FILTER_ENABLED` (default true) strips em dashes, semicolons, and banned filler before construction (`tool_logic.py:278-282`). Logs a `voice_filter violations` warning when it has to rewrite.
- **Quote-reply support.** `reply_to_message_id` flows through every item type via `delivery/whatsapp.py:189-192`, attaching as WA `context.message_id`.
- **CTA auto-degrade.** A `CTAMessage` with >3 buttons is auto-converted to a `ListMessage` in `_render` (`whatsapp.py:198`), keeping the API call legal.
- **Schema-level caps.** `maxItems: 6` on the array, `maxItems: 3` for buttons, `maxLength: 20` for button titles, `maxLength: 24` for list rows, `0.5–4.0` for delays. The brain prompt also says "Max 3 non-delay items per turn" (`whatsapp.py:45`) — schema allows up to 6 (counting delays + media).

## What's broken or missing

- **`send_burst` is NOT in `_IDEMPOTENCY_GUARDED_TOOLS`.** Look at `hooks.py:39-46`. The guarded list covers `log_observation`, `track_open_loop`, `remember`, `attend`, `cancel_attention`, `snooze_attention`. The terminator guard at `hooks.py:192` is a separate check ("turn already terminated"). That's the right design — a duplicate `send_burst` is blocked by terminator logic, not idempotency — but the dual mechanism is non-obvious.
- **Delay clamp asymmetry.** Schema enforces 0.5–4.0, runtime clamps to 0.0–10.0 (`tool_logic.py:196`). Runtime is more lenient than schema — which is fine, but then why have the schema cap?
- **No structural validation that `voice_response` is first.** The schema description says it must be first, the system prompt says first, but `_build_outbound` will accept it anywhere. `voice_synth._collect_text` recovers gracefully (collects all text bodies regardless of position), but a malformed burst still passes.
- **`voice_response` + widget combinations.** `delivery/whatsapp.py` capabilities prompt says "cannot combine with cta, cta_url, list, image, or document" — but nothing actually rejects it. If the model sends both, the audio replaces the text but the widgets get dropped silently because the buffer is rewritten to `[delays..., AudioMessage]` (`voice_synth.py:122`).
- **Empty burst is silent failure.** If the model sends `messages: []`, schema rejects (minItems=1). If items are non-empty but every one is invalid, you get a successful tool result with zero outbound. The user sees nothing. No fallback fires because `trace.has_terminal_tool_call()` returns true.
- **`stay_silent` and `offer` (CLAUDE.md non-negotiables).** Mentioned nowhere in `tools.py`. The only terminator is `send_burst`. If the model truly should stay silent, it has to send a single tiny text item ("k", "noted") — the schema requires at least one message.
- **No proactive single-message rule for ambient chatter.** The system prompt asks for a "tiny fresh acknowledgement" but the schema would happily accept a 6-item burst. The 3-item cap is enforced only by prose, not by schema.
- **`maxItems: 6` is generous.** Includes delays, voice markers, etc. Effective limit is 3 non-delay items by prompt convention, but a model that ignores prompts will get past the schema.

## Opinion — does this match Donna?

The burst architecture is right. WhatsApp messaging has a natural rhythm — a quick reaction, a short text, a beat, a CTA — and the burst encodes that as data. Delays as first-class items is exactly the correct primitive: it lets pacing be part of the reply, not a side-effect. The voice-marker-as-list-item move is also right: voice is just another widget in the burst, with a fallback to text on synthesis failure (`voice_synth.py:174-176`).

The terminator-only contract is sharp. One way to end the turn, enforced by hook, with a synthetic fallback if the model forgets. That's the kind of structural discipline that lets the model stay loose elsewhere.

What feels off: the gap between what the prompt promises (3 items max, voice_response first, no widgets with voice) and what the schema enforces (6 items, position-free, no widget conflict). It works in practice because Sonnet follows the prompt. But the schema should be the source of truth, not the suggestion.

The bigger gap: CLAUDE.md says terminators are `send_burst | stay_silent | offer`. There is no `stay_silent` or `offer`. The doc is wrong, or the spec was simplified and someone forgot to delete the bullet.

## Verdict

- **Architecture: clean.** Single terminator, schema-driven, in-buffer construction, deterministic delivery.
- **Production: hardened.** Double-fire blocked, empty-result fallback wired, voice filter on, voice synth integrated, CTA auto-degrade prevents WA API errors.
- **Gap to vision: schema-vs-prompt drift.** Tighten the schema (3-item cap, voice-first enforcement, voice-widget exclusion) so that a misbehaving model can't ship malformed bursts. Decide whether `stay_silent`/`offer` are real terminators or remove from CLAUDE.md.
