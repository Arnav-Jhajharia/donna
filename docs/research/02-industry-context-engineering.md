# Industry Context Engineering (non-Anthropic)

Source: ctx-industry agent. Condensed.

## Manus — operational playbook (manus.im/blog/Context-Engineering-for-AI-Agents)
- KV-cache is the cost metric. 100:1 input:output. Append-only, deterministic prefixes.
- Mask tools (logit/prefill), do not add/remove — dynamic catalog nukes cache.
- Filesystem as externalized memory; keep restorable pointers only.
- Recitation: rewrite current intent at tail to re-anchor attention.
- Keep errors in context — model recovers better seeing mistakes.
- Avoid few-shot ruts — vary tool-response serialization.

**Donna implication**: put clock / temporal state NEAR THE END of context, never position 0 (breaks cache). Use `tool_choice` masking per mode rather than swapping tools. For multi-step reactive turns, have BRAIN rewrite a tail-anchored intent line.

## Cognition — Don't Build Multi-Agents
- Share full traces, not messages.
- Actions carry implicit decisions; parallel subagents collide.
- Recommend single-threaded linear agents with LLM-based trace compression.

**Donna implication**: validates the BRAIN-loop mandate. The subagent exception is **read-only fan-out returning a compressed artifact**. Never let `dig_deeper` / `compile_brief` / `draft_high_stakes_message` write to the 9 backends — that's where Cognition's critique bites.

## Karpathy / Lütke
- Karpathy 4-bucket taxonomy: **write / select / compress / isolate**.
- Donna's 9 backends = write; tools = select; temporal brief = compress; subagents = isolate.

## Simon Willison
- Raw history, not AI summaries. Memory activates only via explicit invocation.
- **Lethal Trifecta**: private data + untrusted content + external comms. Donna has all three.

**Donna implication**: every tool that touches untrusted WA text needs a PreToolUse guard. Aligns with CLAUDE.md's "no pre-generated situational brief."

## LangChain / LangMem — memory taxonomy
- semantic / episodic / procedural.
- Donna's 9 backends cover all three.
- **Gap identified**: no `recall_similar_situation` tool that pulls 1-3 past episodes as few-shots for high-stakes turns.

## Mem0 / Letta / Zep-Graphiti comparison
- Mem0: vector-first, no temporal.
- Letta/MemGPT: OS-tier model (core/recall/archival) with LLM-paged memory.
- **Zep/Graphiti: bi-temporal graph** — 4 timestamps per fact (t_valid, t_invalid, t_created, t_expired). Outperforms MemGPT on Deep Memory Retrieval.

**Donna implication**: "yesterday" queries should hit Graphiti with `t_valid` filters, NOT scan `chat_messages`. Add a `resolve_time_expression` tool mapping phrases → [t_start, t_end] before retrieval.

## Foundational papers
- **Generative Agents (Park 2023)**: retrieval score = `recency + importance + relevance` (α=1). Reflection triggered when cumulative importance > 150. Importance scored 1-10 by LLM.
- **Reflexion**: verbal self-critique persisted in episodic buffer.
- MemGPT virtual-context, ReAct interleaving.

**Donna implication**: Park's triple-scoring is the ranker for `recall_episodic`. **Importance-accumulation trigger is a clean proactive primitive** — better than time-based polling.

## Tool-bloat threshold (converging evidence)
- Degradation starts ~20 active tools, severe at 40+.
- RAG-MCP: accuracy 43% → 14% at bloated sets.
- Single GitHub MCP: 95% → 71% correct selection.
- Typical MCP install: ~72% of context on tool defs.

**Donna implication**: cap surfaced catalog ≤15 on Haiku. Donna currently at 12-16 depending on mode — right at the edge. Keep when-NOT-to-use clauses to one line each.

## Cursor / Aider / Windsurf
- Dynamic discovery > static context.
- Aider: **PageRank-style ranking with budget** on repo symbols.
- Windsurf codemaps: AI-annotated structural maps fetched on demand.

**Donna implication**: `read_situation_brief` / `refresh_situation_brief` should follow Aider's ranked-slice-with-budget pattern.

## OpenAI / DeepMind
- OpenAI: start single-agent, **trace-grade evals > unit tests**.
- DeepMind Evo-Memory: closest analog to Donna — test-time-learning self-evolving memory benchmark.

## Focus-area answers
1. **Temporal reasoning**: Graphiti `t_valid` filter + `resolve_time_expression` tool.
2. **Proactive triggers**: Park importance-accumulation + event triggers; invoke same loop with `mode="proactive"`.
3. **Tool bloat**: ≤15-20. Consolidate niche variants.
4. **Memory write timing**: sync-write only what next turn needs (open-loop close, profile patch). Async write-back via PostToolUse hooks for Graphiti / Supermemory / embeddings.

## Contradictions flagged
1. **Cognition vs Anthropic subagents**: reconcile — subagents OK if read-only fan-out returning compressed artifact. Reject any subagent that writes.
2. **Willison "no AI summaries" vs Park reflections**: keep reflections as append-only observations with provenance, not replacements.
3. **Manus "keep errors" vs cost discipline**: keep errors *within the turn*, compress out before persistence.
4. **LangChain few-shot episodic vs Manus "no few-shot ruts"**: rotate examples across turns.
