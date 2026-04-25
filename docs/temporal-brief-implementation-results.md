# Temporal Brief Implementation Results

Goal: find the simplest way to give Donna a time-aware mental model without
requiring Supermemory, Graphiti, or changes to Donna Attention.

## Implementations

All five implementations live in `backend/memory/synthesis/temporal_brief.py`
and share the same contract:

`TemporalEvidence -> TemporalBrief`

1. `recent_context`
   - Low saving, low synthesis.
   - Uses recent chat, observations, and open loops.
   - Weak at distinguishing last week vs this week vs next week.

2. `windowed_timeline`
   - Recommended v1.
   - Groups Postgres evidence by user-local week windows.
   - Produces explicit `last_week`, `this_week`, `next_week`, `current_status`,
     `open_loops`, and `stale_or_uncertain`.

3. `attention_weighted`
   - Tool/retrieval leaning.
   - Scores unresolved, upcoming, and recent items higher.
   - Good for "what matters right now", weaker as a full week model.

4. `claude_synthesis`
   - Optional Claude pass over the same timestamped Postgres packet.
   - Falls back to `windowed_timeline` when Anthropic is unavailable.
   - Useful for polish, but not required for the core brief.

5. `compiled_state`
   - High-save variant.
   - Shapes the brief for storage under `users.living_profile.situation_brief`.
   - Best used after the v1 deterministic brief proves useful.

## Stress Test

Command:

```bash
python scripts/stress_temporal_briefs.py
```

Deterministic results:

| Implementation | Avg | Min |
| --- | ---: | ---: |
| `windowed_timeline` | 90.0 | 85.0 |
| `claude_synthesis` fallback | 90.0 | 85.0 |
| `compiled_state` | 83.3 | 75.0 |
| `attention_weighted` | 78.3 | 75.0 |
| `recent_context` | 63.0 | 55.0 |

Live Claude run:

```bash
python scripts/stress_temporal_briefs.py --claude
```

Live Claude scored 83.3 average on the same heuristic set. It was more concise,
but the deterministic `windowed_timeline` retained the expected temporal facts
more reliably.

## Recommendation

Wire `windowed_timeline` first.

Reason: for the situational-awareness task, the hard requirement is not smarter
retrieval. It is preserving user-local time boundaries and rendering the right
evidence in the right bucket. The simplest deterministic implementation did that
best in the stress test.

Use Claude later for one of two jobs:

1. Rewrite the deterministic brief into better prose after the evidence is
   already selected.
2. Judge brief quality during evals, not during every user turn.

## Live Integration Point

`synthesize_and_store_temporal_brief()` writes the selected brief to:

`users.living_profile.situation_brief`

`backend.memory.user_facts.rendering.load_and_render()` now renders that stored
situation brief into Donna's initial runtime context.

## Implemented Tooling

Backend memory tools:

- `log_observation`: writes timestamped observations and accepts explicit
  `event_time` for events that happened earlier than the current message.
- `track_open_loop`: writes unresolved commitments, decisions, errands, and
  follow-ups.
- `close_open_loop`: marks an open loop closed.
- `refresh_situation_brief`: regenerates the deterministic temporal brief and
  stores it in `users.living_profile.situation_brief`.
- `read_situation_brief`: reads the stored temporal brief for tests, jobs, and
  diagnostics.

High-signal write tools now refresh the situation brief best-effort after the
write commits:

- `log_observation`
- `track_open_loop`
- `close_open_loop`

Claude's default runtime tool list still exposes only narrow writes:

- observations
- open loops
- open-loop closure

It does not expose direct `living_profile` mutation. The backend owns temporal
brief compilation.

## Eval Commands

Local memory/runtime suite:

```bash
python -m pytest tests/test_donna_runtime.py backend/tests -q
```

Synthetic temporal stress test:

```bash
python scripts/stress_temporal_briefs.py
```

Live E2E memory pipeline:

```bash
DONNA_E2E=1 python -m pytest tests/test_integration_end_to_end.py -v -s
```

Refresh active users' stored situation briefs:

```bash
python scripts/refresh_situation_briefs.py --dry-run --limit 10
python scripts/refresh_situation_briefs.py --limit 10
```

Recommended nightly command:

```bash
python scripts/refresh_situation_briefs.py --active-days 14 --concurrency 4
```

Export redacted real traces for future eval construction:

```bash
python scripts/export_temporal_eval_traces.py --limit 50 --out /tmp/donna_temporal_traces.jsonl
```

The export defaults to `--content-mode redact`. Use `--content-mode raw` only
for local manual review.

Expanded synthetic temporal dataset:

```bash
python scripts/stress_temporal_briefs.py --dataset diverse
python scripts/stress_temporal_briefs.py --dataset all
```

The expanded dataset lives in
`backend/memory/synthesis/temporal_eval_dataset.py`.

It currently covers:

- 16 user archetypes
- 8 overloaded/noisy-history variants
- 12 timezones
- observation, open-loop, calendar, and chat evidence for every diverse case

Expanded results after salience filtering inside the deterministic week buckets:

| Dataset | Implementation | Avg | Min | Cases |
| --- | --- | ---: | ---: | ---: |
| `diverse` | `windowed_timeline` | 86.2 | 85.0 | 24 |
| `diverse` | `attention_weighted` | 85.0 | 85.0 | 24 |
| `diverse` | `recent_context` | 46.6 | 37.0 | 24 |
| `all` | `windowed_timeline` | 86.7 | 85.0 | 27 |
| `all` | `compiled_state` | 85.9 | 75.0 | 27 |
| `all` | `attention_weighted` | 84.0 | 69.0 | 27 |
| `all` | `recent_context` | 48.4 | 37.0 | 27 |

The noisy-history cases exposed one important bug: the low-signal filter was
matching `"k"` as a substring, which accidentally marked words like "week" as
low signal. That is fixed; low-signal matching is now exact for short ambient
messages and explicit for synthetic noise phrases.
