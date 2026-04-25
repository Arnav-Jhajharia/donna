# Anthropic-Sourced Context Engineering

Source: ctx-anthropic agent. Citations in-line.

## 1. Prompt caching — hard facts
- Cache order: `tools → system → messages`.
- **Max 4 `cache_control` breakpoints** (one auto-consumed).
- **Haiku 4.5 floor: ≥4096 tokens**. Below the floor, caching SILENTLY FAILS.
- TTL: 5-min (1.25× write), 1-hr (2× write). Reads 0.1× base.
- 1-hr entries MUST precede 5-min when mixed.
- Lookback: 20 blocks per breakpoint.
- Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching

**Donna mandate**: 3 breakpoints in order: `tools` (1-hr) | `system_after_persona` (1-hr) | `messages_last_stable` (5-min auto). If persona+rules < 4096 tokens, PAD to clear the floor. Never place per-turn data before a breakpoint.

## 2. Tool descriptions
- "Self-contained, robust to error, extremely clear"; avoid "bloated" / "ambiguous decision points."
- Describe "as you would to a new team member, making implicit context explicit."
- Prefer consolidated tools (`schedule_event` over 3 atomic tools).
- Return HIGH-SIGNAL content — strip UUIDs, use semantic names.
- `tool_choice`: `auto` 346 tokens, `any`/forced 313 (negligible).
- Source: https://www.anthropic.com/engineering/writing-tools-for-agents

## 3. Loop design
- Poka-yoke: make bad calls structurally impossible (absolute IDs, not names).
- Errors must be "actionable improvements, not opaque codes."
- Source: https://www.anthropic.com/engineering/building-effective-agents

## 4. Subagents
- Multi-agent Opus+Sonnet: "90.2% perf improvement, 15× more tokens."
- Token usage "alone explains 80% of performance variance."
- Subagent = "side task would flood the main conversation."
- Briefing must carry compressed situation, NOT the Living Profile (orchestrator owns cache).
- Source: https://www.anthropic.com/engineering/multi-agent-research-system

## 5. System-prompt structure
- Use `<section>` tags or Markdown. Anthropic example: `<background_information>`, `<instructions>`, `## Tool guidance`.
- Put mode/per-turn-varying content LAST (after breakpoint).
- Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

## 6. Memory: just-in-time > preload
- "Lightweight identifiers...dynamically load via tools."
- "Every new token introduced depletes the attention budget."
- DIRECTLY validates CLAUDE.md's no-pre-brief rule.

## 7. Evals
- "Grade what the agent produced, not the path it took" (when possible).
- Judge "return Unknown when insufficient info" — reduces hallucinated justifications.
- Isolate dimensions — one judge per rubric.
- For deterministic rules (em-dash, lowercase), use CODE-based graders, not LLM.
- Source: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

## 8. Hooks
- SDK hooks are callbacks keyed to: PreToolUse, PostToolUse, Stop, SessionStart/End, UserPromptSubmit, SubagentStart/Stop, PreCompact, PostCompact.
- PreToolUse can BLOCK (deny+reason fed back to model).
- PostToolUse CANNOT UNDO.
- `SessionStart` with `compact` matcher = canonical re-inject pattern.
- Multiple PreToolUse rewrites same input: "last to finish wins" — never chain two.
- Source: https://code.claude.com/docs/en/hooks-guide

## 9. Extended / interleaved thinking
- Anthropic directly: "Skip extended thinking for real-time reactive use cases."
- On Opus 4.6+ / Sonnet 4.6, auto-enabled via `effort` param.
- Thinking blocks removed from context but count as cached input tokens.
- Source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking

**Donna mandate**: OFF for reactive WhatsApp turns. Enable only in Opus subagents (compile_brief, draft_high_stakes_message) where latency is hidden.

## 10. Misc high-leverage
- `SessionStart: compact` hook for re-injecting open-loops + calendar after auto-compaction.
- `strict: true` on tool schemas guarantees conformance.
- Cache isolation: workspace-level (Feb 2026).
- Tool-use system prompt: 346 tokens with `tool_choice=auto`.
- Small description refinements drove Sonnet 3.5 SWE-bench SOTA — version-control descriptions as first-class artifacts.
