# 05 — The BRAIN loop

## What's there

The whole reactive/proactive turn machinery lives in five files inside `donna_runtime/`:

- `brain.py` (116 lines) — `donna_turn(state, config)` entry. Resolves session, renders per-turn context, calls the SDK, captures outbound, persists.
- `runner.py` (304 lines) — `traced_donna_turn` (LangSmith wrap) → `_donna_turn_core` (the actual SDK `query()` async iterator at `runner.py:121`).
- `options.py` (89 lines) — `build_options` packs the SDK config: model, system prompt, MCP server with all donna tools, hooks, allowed/disallowed tools, `max_turns`, `resume`, `fork_session`.
- `tools.py` (2532 lines) — 28 MCP tools registered in `DONNA_TOOLS` (`tools.py:2505`). `send_burst` is last and is the only terminator.
- `hooks.py` (555 lines) — `pre_tool_hook` and `post_tool_hook` wrap every tool call.
- `post_call.py` — runs the brain again after a voice call ends, pulling the transcript as input.

`mode` lives on `DonnaAgentConfig` (`config.py:144`) as `Literal["reactive", "proactive"]`. Default `max_turns=6`, `proactive_max_turns=12`.

## What works

- **Single SDK loop, no framework wrap.** `runner.py:121` literally does `async for message in query(prompt=wrapped_prompt, options=options)` and routes each message into `TurnTrace`. No LangGraph, no perceive-act, no second framework — matches CLAUDE.md.
- **Session resume + recovery.** `brain.py:39-42` resolves a saved Claude session for the user; `brain.py:79-91` detects a poisoned resume (zero tool calls + empty buffer) and retries fresh once, emitting a `retry_fired` event. `runner.py:239-246` provides a second fallback for missing-session errors.
- **Stateless mode.** `DONNA_STATELESS_SESSIONS=1` makes the SDK run as a pure tool-use loop with no resume; chat history is reconstructed by `context_builder._safe_recent_chat`. This is the production path.
- **Outbound capture.** `_OUTBOUND_BUFFER` is a `ContextVar[list]` (`hooks.py:21`). The runner installs a buffer, `send_burst` extends it via `tool_logic.send_burst_result`, the brain reads `_outbound` off state.
- **Terminator guard.** `pre_tool_hook` (`hooks.py:192`) blocks a second `send_burst` in one turn with `permissionDecision: "deny"`.
- **Idempotency guard.** `_IDEMPOTENCY_GUARDED_TOOLS` (`hooks.py:39`) blocks repeat writes (`remember`, `track_open_loop`, `attend`, etc.) with identical args via SHA-hashed signatures per turn.
- **Plain-text fallback.** `runner._fallback_plain_text_to_send_burst` synthesizes a `send_burst` from plain final text when Sonnet forgets the terminator. The trace records it as a synthetic call so production still ships an outbound message.
- **Failure floor.** On any SDK exception (`brain.py:99`) state is set to a single `TextMessage("hm, one sec")` so the user is never silently dropped.
- **Per-turn cost discipline.** `build_options` disables built-in CLI tools (`tools: ""`), skips slash-command descriptions, excludes dynamic system-prompt sections — all to keep the prefix cache stable. `cache_ttl_1h=True` by default.

## What's broken or missing

- **`mode` is barely wired.** `DonnaAgentConfig.mode` exists, the dispatcher sets `mode="proactive"` (`proactive/dispatcher.py:368`), but `proactive_max_turns=12` is never read anywhere in `donna_runtime/`. Reactive `max_turns=6` is used for both. Search confirms zero callsites for `proactive_max_turns`.
- **CLAUDE.md says terminators are `send_burst | stay_silent | offer`.** Only `send_burst` exists. `TERMINATOR_TOOL_SUFFIXES = ("send_burst",)` (`tracing.py:10`). `stay_silent` and `offer` are mentioned nowhere in `tools.py`.
- **`runner.run_messages` is a CLI-era leftover.** It saves to a `session_store_file` JSON path (`session_store.save_user_session`) that production doesn't use. Live brain calls go through `brain.donna_turn` and DB-backed `save_user_session_db`.
- **Two `donna_turn` symbols.** `runner.donna_turn` (legacy CLI helper, `runner.py:32`) and `brain.donna_turn` (production). Imports are unambiguous but the duplicate name is confusing.
- **No per-turn budget alarm.** `request_timeout_s=45.0` is the only ceiling. There is no token-cost cap, no warning when a turn cycles `recall` then `smart_recall` then `recall_episodic`.
- **Trace persist is best-effort.** `brain.py:109-112` swallows any persistence failure silently. Fine for prod, but it means evals can lose data without a signal.

## Opinion — does this match Donna?

It does. The loop is genuinely the SDK loop, not a wrapper around it. The brain file is 116 lines because most decisions belong in tool descriptions and the system prompt. Recovery is opinionated — one clean retry, then a one-line voice fallback, no retry-storm. The terminator-guard and idempotency-guard are exactly the kind of cheap deterministic safeties that a thinking-partner agent needs so the model can stay loose without writing duplicate observations.

The thing that doesn't match: CLAUDE.md still talks about `stay_silent` and `offer` like they exist. They don't. Either the doc is stale (per MEMORY.md, that's the standing read) or the design has been simplified and someone needs to cross out those bullets. `proactive_max_turns` being declared and never consumed is the same kind of drift.

## Verdict

- **Architecture: solid.** Single loop, clean recovery, minimal surface. Faithful to the non-negotiables.
- **Production: working.** Every reactive WhatsApp turn and every escalated proactive event lands here. The 45s timeout and the plain-text fallback have already saved bad turns.
- **Gap to vision: small.** Drop `stay_silent`/`offer` from CLAUDE.md or implement them. Wire `proactive_max_turns`. Otherwise the loop is the cleanest part of the codebase.
