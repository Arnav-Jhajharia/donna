# Proactive loop eval report

_Generated 2026-04-21T08:13:46.073977+00:00_

| eval | target | measured | pass |
|---|---|---|---|
| shadow_tick_latency | < 5000 ms for 10 shadows | 6.0 ms | OK |
| promotion_decay | ≥ 50% archived when signal absent | 10/10 = 100% | OK |
| duplicate_suppression | 0 new shadows on second run | run1 authored=1, run2 authored=0 | OK |
| offer_idempotency | accept/reject no-op on non-OFFERED statuses | all guards held | OK |

**4/4 passed.**
