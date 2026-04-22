# Open Questions (spec §13)

Tracked items deferred out of the memory port. Resolve in follow-up cycles.

## Tool-surface consolidation

The current surface exposes 13 tools (9 read + 4 write). Several could fold
into `smart_recall` (`recall_episodic`, `recall_graph`,
`recall_document_chunks`). Before consolidating: measure actual model
selection patterns across ≥500 turns and only fold tools the model picks
<5% of the time.

## Gate threshold tuning

The selectivity gate targets a 40–60% ingestion rate. We do not yet have
production data to validate this band. After ≥20 real turns, compute the
ratio from `DONNA_GATE_LOG` and adjust the fast-accept / fast-reject rule
sets. See [docs/memory.md](./memory.md) for the tuning steps.

## Scheduler wiring

`synthesize_nightly_profile` and `synthesize_tier2_rules` are plain async
callables. Production needs a scheduler (APScheduler or cron) to fire them
per user per night in their local TZ. Out of scope for the port.

## Procedural rules storage shape

`ProceduralRule` stores the full rule as a text blob (`WHEN ...\nTHEN ...`).
Consider splitting into `when` / `then` / `rationale` columns if the rules
need to be queried by trigger keyword.

## Living Profile backfill

Initial migration does NOT copy `user.facts['nightly_profile']` into the
new `users.living_profile` column. First-night synthesis will populate
`users.living_profile`; until then, runtime falls back to the seed.

## Supermemory vs Graphiti search overlap

Both stores search for facts. Empirically we have not measured where
Graphiti adds signal beyond Supermemory's hybrid hits. Need an A/B slice
on recall quality before locking tool selection.

## Observation types as trackers

`read_tracker` tool maps to `list_observations(type=...)`. The old surface
had named trackers (`expenses_week`) pre-populated. We need a stable
ontology of observation `type` values so the model can discover available
trackers, rather than guessing strings.
