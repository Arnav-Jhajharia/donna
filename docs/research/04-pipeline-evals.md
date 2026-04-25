# Pipeline Evals — SOTA 2025-2026

Source: evals-research agent.

## Trajectory / trace evals
- LangSmith `agentevals`: trajectory exact/subset/superset + LLM-judge.
- Arize Phoenix (OTel-native), Braintrust (CI gating), Galileo, W&B Weave.
- Metrics: tool-call precision/recall, step-correctness, trajectory similarity, argument fidelity.
- For Donna: **exact match on terminator selection** (send_burst vs stay_silent); **LLM-judge on reasoning path**.

## LLM-as-judge rigor
- Shi et al. 2025 (arxiv 2406.07791): position bias is not random — correlates with quality gap.
- **Pairwise > scalar** (higher human agreement).
- **Swap-and-average** (A|B and B|A) kills position bias.
- Cascaded Selective Evaluation (ICLR 2025): cheap judge → stronger on low-confidence. Human-agreement <60% → ~80%.
- **Stronger-model-as-judge validated** but "super-consistent" judges (exceeding human-to-human) are overconfident red flag.
- Mandate: Opus-judges-Haiku for voice/subjective; calibrate quarterly against 100 human labels (Cohen's kappa).

## Golden datasets
- Start **15-30 real/synthetic items**. Grow to 100-300 once taxonomy stabilizes. 1000+ only at launch.
- Every production bug → new golden item.
- **Fixture requirement**: each item needs seeded Postgres + Graphiti subgraph + Supermemory chunks + Living Profile JSON. No fixture = no reproduction of "she forgot my mom's surgery."

## Whole-pipeline layers
| Layer | Metric |
|--|--|
| Ingress | parse accuracy, intent label |
| Memory retrieval | Recall@k, MRR, nDCG per backend |
| Tool selection | precision/recall, correct-tool |
| Hook side-effects | did-fire, idempotent |
| Egress voice | hard regex + rubric judge |
| E2E goal | LLM judge + human spot-check |

## CI cadence
- Per-PR smoke (15-30 items, <5 min, <$0.50).
- Pre-deploy full (~300 items).
- Nightly adversarial.
- Weekly human review of 50 sampled prod traces.

## Memory evals
- LongMemEval (arxiv 2410.10813) — 500 QA, 5 tasks incl temporal + abstention.
- LoCoMo (arxiv 2402.17753) — 300 turns, 9k tokens, 35 sessions per conv.
- Zep: 63.8% vs Mem0 49% on LongMemEval/GPT-4o.
- Mem0 v2: 91.6 LoCoMo / 93.4 LongMemEval at <7k tokens/retrieval.
- **Build Donna-LongMemEval**: ~200 items covering multi-session, temporal, contradiction, open-loop-closure.
- Measure "right moment" separately from "right data" — was tool called at the right turn?

## Voice / persona
- Hard rules → regex lint in CI (em-dash count, semicolon count, banned phrases "I understand", "Great question", "AI assistant"). Zero tolerance.
- Soft rubric → TwinVoice/PersonaLens 3-pillar (Opinion Consistency, Logical Fidelity, Stylistic Similarity), 1-5 anchored.
- Pairwise Donna-vs-vanilla-Claude. Target >90% "more Donna" win.
- PersonaEval: best models only 69% persona identification — multiple seeds + aggregate.

## Adversarial
- Indirect prompt injection via contacts (Lakera, spotlighting/structural prompting).
- Memory poisoning via `log_observation`, `update_living_profile` (Microsoft, Unit 42 flagged).
- Cross-MCP-server poisoning.
- Long-horizon goal hijacking.
- Tooling: PyRIT (Microsoft), Garak (NVIDIA), Promptfoo red-team, MITRE ATLAS.
- **Donna nightly suite**: (1) injected WA message must flag_attention not execute; (2) poisoned Graphiti fact → abstain/contradict; (3) "system prompt" impersonation; (4) injection at turn N doesn't change behavior at N+10.

## Cost / latency as first-class
- p95 < 1s for user-facing.
- Track p95/p99 not median — tails concentrate cost.
- Cache hit rate as explicit metric.
- Scorecard: p50_latency_ms, p95_latency_ms, cost_per_turn, cache_hit_rate, max_turns_hit_rate.
- CI gates: fail if p95 > 2× baseline OR cost > 1.5× baseline.

## Online monitoring
- Sample 1-5% prod → LLM-judge near-real-time drift.
- Implicit: user reply latency, "wait what?", abandonment, re-ask rate.
- Weekly annotation queue: 50 traces stratified by (low judge confidence, frustration signal, cost outlier).

## Disagreements
- Exact-trajectory vs LLM-judge: use BOTH (strict on terminators, judge on reasoning).
- Mem0 vs Zep benchmarks contradict each other — run Donna-LongMemEval before committing.
- Dataset size: start small (30) > 1000 noisy — Hamel/Shreya position.
