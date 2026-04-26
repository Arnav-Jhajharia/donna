# Attention × Observations alignment plan

Status: **phase A in progress** (2026-04-24). Phases B–E queued.

Donna's moat is attention. Attention is useless if the observations it reads are schema-incoherent. This plan aligns the two and enables proactive offering.

---

## Problem

Two tangled failures:

1. **Schema drift.** `log_observation` stores whatever keys the BRAIN loop's Haiku picks (`calories` one day, `kcal` the next). Attention tick reads back and has to guess. Dedup keys, aggregates, aliases silently wrong.
2. **No proactive agency.** Donna never offers to track/watch/brief/prep. Everything is user-declared.

(1) blocks (2). You can't reliably offer "track your Grab spend" if you can't count Grab spend reliably first.

---

## Design space

| Option | Summary | Verdict |
|---|---|---|
| **A. self-contained** | Attention gets its own typed store, separate from observations | Rejected — forks the memory system, duplicates data |
| **B1. offer-first** | Donna suggests tracking X → user accepts → schema locked → observations validated | Half the answer |
| **B2. observation-first** | User logs freely → scanner watches → attention shadow-infers and offers to promote | The other half |
| **B1 + B2 via schema registry** | **Chosen** — observation table stays schemaless-at-heart; every `(user_id, type)` gets a registry row that write-time validation and tick-time aggregation consult | This is the plan |

---

## Architecture

```
WhatsApp in → BRAIN loop → log_observation(type, fields)
                                   │ 1. lookup observation_schemas[user_id][type]
                                   │ 2. if exists: coerce via aliases + canonical_fields
                                   │ 3. else: register inferred schema
                                   │ 4. on new key: additive extension + drift log
                                   ↓
                         observation_schemas (single source of truth)
                                   ↑
                                   │ attention ticks read aliases to normalize
                                   │
Pattern detector → scans observations + chat + calendar + loops
                 → emits OfferCandidate
                 → creates Attention(status=SHADOW)
                 → shadow ticks accumulate evidence
                 → promotion_criteria met → status=OFFERED
                 ↓
surprise tool — kind=offer_attention → WhatsApp opt-in burst
                 ↓ (on "yes")
attention → LIVE; schema → confirmed
```

---

## Phases

### Phase A — write-time alignment (foundation) **— in progress**

- New `observation_schemas` table (revive-and-reshape the dead `SchemaRegistry`).
- Modify `log_observation` to lookup / coerce / register.
- Drift-signal via structured log.
- No user-visible behavior change.

Est: ~150 LOC + 1 migration + 5 tests.

### Phase B — pattern detector + shadow auto-creation

- `donna_runtime/pattern_detector.py` with five signal rules (obs frequency, entity recurrence, query repeat, calendar recurrence, stale loops).
- Hourly cron + reactive hook on `log_observation`.
- Shadow attention creation via existing `donna/attention/author.py`.
- Promotion criteria vocabulary + evaluator.
- Shadows run silent; no user-visible change.

Est: ~300 LOC + 15 tests.

### Phase C — offer tool (user-visible)

- Extend `surprise` tool with `offer_attention` kind.
- Reply capture for yes / no / later in BRAIN loop.
- First WhatsApp offers land.

Est: ~200 LOC + 10 tests.

### Phase D — backfill existing observations into schemas

- One-shot migration script.
- Groups existing rows by `(user_id, type)`, infers modal `canonical_fields`, writes rows.

Est: ~80 LOC + validation against prod data.

### Phase E — terminology expansion (ties to attention issues #6–#10)

- Domain hints for India / SG.
- New `DomainTag` buckets (`TAX`, `REGULATORY`, `HOUSING`, `BANKING`, etc.).
- Currency field on `SurfacePolicy`.
- Multilingual `subject_pattern` lexicon.

---

## observation_schemas table

```python
class ObservationSchema(Base):
    __tablename__ = "observation_schemas"
    id: UUID
    user_id: str                      # FK users
    type: str                         # matches Observation.type
    canonical_fields: JSONB           # {"kcal": "int", "meal": "str"}
    aliases: JSONB                    # {"calories": "kcal", "energy": "kcal"}
    created_at: datetime
    updated_at: datetime
    # Unique index on (user_id, type)
```

**Semantics:**
- First write auto-creates; `canonical_fields` inferred from the first observation's fields.
- Subsequent writes coerce keys via `aliases`.
- Unknown keys are added to `canonical_fields` additively and logged as drift (`observation_schema.drift_detected`).
- Attention read path (extractor prompt) gets the aliases as a normalization hint.
- Phase C promotion flips nothing here; confirmation is an implicit property of "an attention references this schema".

---

## Guardrails / evals

- Drift rate per 1k observations (target: trending down after phase A).
- Field-name entropy per `(user_id, type)` (target: 1 stable mode after 20 writes).
- Pattern detector precision (manual review, target ≥70%).
- Shadow → OFFERED conversion (target ≥30%).
- Offer reply rate (target ≥50% within 72h).
- "Stop offering" rate (hard circuit-breaker at 5% per week).

---

## What we are NOT doing

- No new orchestration framework.
- No new memory backend.
- No chained LLM calls outside BRAIN (pattern detector is rule-based + single author call per candidate).
- No typed Pydantic classes per observation type (too much lock-in).
- No real-time offer streaming (offers are end-of-turn terminators only).
- No global schema registry (per-user only).

---

## Open questions (tracked)

1. Offer cap split — share surprise budget or dedicated? **Lean: share, per-kind cap of 1/week for offers.**
2. Reply capture — dedicated tool vs natural-language Haiku? **Lean: dedicated enum tool, Haiku fallback.**
3. Alias auto-confirmation — auto-alias on high similarity, else confirm? **Lean: yes, threshold ~0.9.**
4. Schema evolution after confirmed — additive only? **Lean: yes; renames require confirmation.**
5. Shadow retention — expire unpromoted shadows? **Lean: `quietly_archived` after 60d.**
6. Backfill aggressiveness — which existing `(user_id, type)` pairs to backfill? **Lean: ≥5 observations, `inferred` status only.**
