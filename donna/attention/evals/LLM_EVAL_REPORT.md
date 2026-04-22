# Proactive loop — LLM-gated eval report

_Generated 2026-04-21T10:13:57.415907+00:00_

| eval | target | measured | samples | pass |
|---|---|---|---|---|
| proposer_precision | ≥ 0.80 | 3/3 = 100% (suppressed_rejects=2, missed_accepts=0) | 5 | OK |
| proposer_recall | ≥ 0.70 | pending — needs signal-injection shims | 2 | FAIL |
| hit_calibration | agreement ≥ 0.85 | 4/4 = 100% | 4 | OK |
| conversion_time | median ≤ 500 ms per shadow (deterministic path) | 1.2 ms avg (5/5 offered) | 5 | OK |
| author_retry_rate | ≤ 0.15 | 0/5 = 0% | 5 | OK |
| cost_per_cycle | mean ≤ $0.01 | mean=$0.00468 max=$0.00481 n=5 | 5 | OK |

**5/6 passed.**
