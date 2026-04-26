# Observability Pass — Implementation Plan

**Date:** 2026-04-25
**Branch:** phase-1-usable
**Scope:** runtime observability only. Voice/audio is shipped and confirmed
working in a prior session — no further audio work in this plan.

## Goal

Close three gaps in current observability so debugging "what did Donna do on
turn X" stops requiring grep across multiple files:

1. **Model preamble text** — text content blocks the model emits between
   tool calls are captured in the trace but never emitted as observability
   events. They tell us model intent vs action.
2. **Tool result payloads** — we log `tool.call` (input) but never the tool's
   actual return value. Debugging a `recall` that fetched 8 hits and only
   used 1 is currently blind.
3. **Anthropic API usage** — token counts, cache hits, stop_reason, per-call
   latency. Already partially captured in `TurnTrace`, never emitted as
   observability events.

Plus a render layer: a single-turn timeline view that takes a `turn_id` and
renders every event in chronological order with timing.

Goal is **single-turn forensics, not fleet aggregates.** Fleet aggregates
already live in LangSmith — don't rebuild that.

## Event taxonomy additions

All events share `event`, `ts`, `turn_id`, `user_id`, `schema_version`
(already enforced by `observability.emit`).

| Event | When | Fields |
|---|---|---|
| `model.preamble` | runner sees a `TextBlock` in `AssistantMessage.content` | `text` (truncated to 4000 chars), `block_index`, `total_blocks` |
| `tool.result` | `post_tool_hook` runs (PostToolUse) | `tool`, `tool_short`, `call_id`, `status` (ok/error), `result_preview` (truncated), `duration_ms` (from PreToolUse → PostToolUse delta) |
| `model.usage` | runner sees a `ResultMessage` | `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `total_cost_usd`, `stop_reason`, `latency_ms` (turn-end vs turn-start) |
| `boundary.call` | optional later — wraps httpx calls to ElevenLabs / Deepgram / WA media upload | `name`, `status_code`, `latency_ms`, `error_class` |

Bump `_SCHEMA_VERSION` to `2` because we're adding new event types. Existing
event readers must keep working — only adding, never renaming.

## File-by-file changes

### `donna_runtime/observability.py`

- Bump `_SCHEMA_VERSION = 2`
- Add docstring entries for the three new events under "Event types"
- Add helper `emit_model_preamble(text: str, block_index: int, total_blocks: int)`
- Add helper `emit_tool_result(tool_name: str, status: str, result_preview, duration_ms: int | None, call_id: str | None)`
- Add helper `emit_model_usage(usage: Mapping | None, latency_ms: int | None, stop_reason: str | None, total_cost_usd: float | None)`
- Re-use existing `_preview_value` for payload truncation
- Don't change existing emitters

### `donna_runtime/runner.py`

In `_record_message`:

- For `AssistantMessage`: when iterating `block in message.content`, count
  `text_blocks = [b for b in message.content if isinstance(b, TextBlock)]`,
  then for each `TextBlock` call `emit_model_preamble(block.text,
  block_index=i, total_blocks=len(text_blocks))` alongside the existing
  `trace.record_thought(...)`. Keep existing behavior intact.
- For `ResultMessage`: after `trace.record_usage(...)`, call
  `emit_model_usage(usage=getattr(message, "usage", None),
  latency_ms=<turn duration so far>, stop_reason=<best-effort>,
  total_cost_usd=getattr(message, "total_cost_usd", None))`. The latency
  comes from a `time.time()` recorded in `_donna_turn_core` at start.

### `donna_runtime/hooks.py`

In `post_tool_hook`:

- Compute `duration_ms` from PreToolUse start time. Need a small ContextVar
  or in-trace lookup keyed by `call_id`. Simplest: a turn-scoped dict
  `_TOOL_CALL_STARTS: ContextVar[dict[str, float]]` set in `pre_tool_hook`
  and read in `post_tool_hook`. Reset in `trace_hook_context`.
- Emit `tool.result` event with `tool_response` already passed in via
  `input_data["tool_response"]`. Truncate via existing `_preview_value`.
- Don't disturb existing image-specific path (`_image_post_tool_record`).

### `donna_runtime/timeline.py` (NEW)

Read `_OBS_LOG_PATH` (default `.donna/events.jsonl`), filter by `turn_id`,
return ordered list of events. ~80 lines including:

- `read_events(turn_id: str, log_path: Path | None = None) -> list[dict]`
- `format_timeline(events: list[dict]) -> str` — renders aligned text,
  one line per event, with relative timestamps from turn.start

### `scripts/donna_trace.py` (NEW)

Tiny CLI:

```
$ python -m scripts.donna_trace turn_1745568712345
+0ms     turn.start         user_message_len=23 model=claude-haiku-4-5
+12ms    prompt.snapshot    system_prompt_len=4821 wrapped_user_prompt_len=312
+820ms   model.preamble     #1/2 "ok let me check her calendar first"
+831ms   tool.call          check_calendar
+845ms   tool.result        check_calendar status=ok preview="next 24h..." duration=14ms
+1240ms  model.preamble     #1/1 "got it. she's free at 8am, suggesting that"
+1255ms  tool.call          send_burst types=[voice_response,text]
+1267ms  tool.result        send_burst status=ok
+2150ms  model.usage        in=4821 out=187 cache_read=4500 cost=$0.0021
+2155ms  turn.end           tools=[check_calendar,send_burst] terminal_ok=true
```

~30 lines. argparse `turn_id`, calls `read_events` + `format_timeline`,
prints. Optional `--json` flag dumps raw events.

### Tests

`tests/test_observability_emissions.py` (NEW):

- `emit_model_preamble` writes correct event shape
- `emit_tool_result` truncates large payloads
- `emit_model_usage` handles missing usage gracefully

`tests/test_timeline.py` (NEW):

- `read_events` filters by turn_id
- `format_timeline` produces stable output for a fixture event sequence
- Out-of-order events sort by ts

`tests/test_runner_observability.py` (NEW):

- Mock SDK message stream with TextBlock + ToolUseBlock + ResultMessage
- Assert `model.preamble`, `tool.call`, `model.usage` events all emit
- Use `_OBS_LOG_PATH` override pointing at tmp_path

## Out of scope

- Fleet aggregates / dashboards over time (LangSmith already does this)
- Real-time websocket streaming (overkill, just tail the JSONL)
- Boundary timing for memory backends (already partially via
  `instrument_memory_op`; deferred)
- Sentry / external APM integration (separate decision)
- Schema migration tooling (we just bump the version, old events stay valid)
- `boundary.call` event for ElevenLabs / Deepgram / WA — defer until needed;
  current httpx logs are sufficient for the tonight's-voice-bug class of
  problems

## How to resume in a fresh session

1. Read this file: `docs/superpowers/specs/2026-04-25-observability-pass-plan.md`
2. Read these files for context: `donna_runtime/observability.py`,
   `donna_runtime/runner.py`, `donna_runtime/hooks.py`,
   `donna_runtime/tracing.py`
3. Implement in this order: `observability.py` helpers → `hooks.py` PostToolUse
   wiring → `runner.py` preamble + usage emissions → `timeline.py` →
   `scripts/donna_trace.py` → tests
4. Run `python -m pytest tests/test_observability_emissions.py
   tests/test_timeline.py tests/test_runner_observability.py
   tests/test_donna_runtime.py` after each step

## Existing infra to reuse

- `observability.emit(event, **fields)` — handles JSONL write, ContextVar
  scoping, never raises
- `observability._preview_value(value, max_chars=4000)` — payload
  truncation
- `turn_span(turn_id, user_id)` — already binds turn_id into all events
- `_OBS_LOG_PATH` — env-overridable via `DONNA_OBS_LOG`

## Voice/audio status (do not re-touch)

Voice end-to-end works. Three-layer defense in place:
runtime-context directive, PreToolUse marker injection, voice_synth
force-trigger. Confirmed in production at 05:14:30 with logs:
`send_burst.invoke: types=['voice_response', 'text']` →
`voice synth: voice_response marker detected, synthesizing` →
ElevenLabs 401 (sole remaining issue: user must toggle Text to Speech
permission scope on ElevenLabs dashboard — not a code issue).
