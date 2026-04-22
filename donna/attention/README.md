# Attention Harness

End-to-end pipeline that turns a raw user intent (e.g. *"keep an eye on Poke"*,
*"remind me 2 hours before any flight"*) into an executable **AttentionSpec** —
Donna's standing instruction to watch ambient signal, extract updates on a
cadence, and surface them through a rule-based policy.

```
intent → normalize → retrieve → author → dry_run
```

## The Attention primitive

An **Attention** is a card-shaped standing query. The `card` field fixes the
update shape; the LLM authors semantics.

| Card          | Shape of update                              | Example intent                          |
|---------------|-----------------------------------------------|-----------------------------------------|
| `event_stream`| discrete updates about a subject              | "keep an eye on Poke"                   |
| `tally`       | rolling count / aggregate                     | "track my subscriptions"                |
| `brief`       | one synthesized artifact per cadence          | "summarize my week every Friday"        |
| `prep_doc`    | pre-event context                             | "brief me before 1:1 with Sarah"        |
| `open_loop`   | track a thread awaiting resolution            | "close the loop on investor replies"    |
| `ping`        | degenerate one-shot / recurring reminder      | "remind me to call mom at 6pm"          |

## Guiding principle (non-negotiable)

Donna watches **ambient signal** (email, calendar, shipments, news, releases,
tweets) plus **user-originated** inputs (self-logged observations, elicited
replies). She **never** reads user-organized workspaces (Notion, Linear,
Airtable, Trello, Asana, ClickUp) — those are where the user has already done
the work Donna exists to do for them.

## Scope cuts (v1)

- **15 gold examples** covering all 6 cards × core domains. Second-slot
  fill-ins deferred.
- **Pure-Python TF-IDF retrieval** (no sklearn / Voyage dep). Swap to Voyage
  when `VOYAGE_API_KEY` wiring is added.
- **Fetchers stubbed from fixtures**, except `calendar_events` (wires through
  to `backend/memory/tools/list_calendar.py` when a live `user_id` is supplied).
- **Shadow runtime** designed in the schema but not yet ticked by a scheduler.

## Run

```bash
pytest donna/attention/tests/                     # 122 tests
python -m donna.attention.cli "keep an eye on Poke"
python -m donna.attention.cli "remind me 2 hours before any flight"
python -m donna.attention.cli "summarize my week every Friday evening"
```

The CLI prints `[NORMALIZE] [RETRIEVE] [AUTHOR] [DRY RUN] [TOTAL]` stage
blocks with timings and a rendered markdown preview.

## Modules

| File                        | Purpose                                          |
|-----------------------------|--------------------------------------------------|
| `vocabulary.py`             | Closed enums (`SourceType`, `CardType`, params). |
| `schema.py`                 | Pydantic `AttentionSpec` + `Attention` record.   |
| `examples/gold_specs.py`    | 15 `GoldExample` records used for few-shot.      |
| `normalize.py`              | Haiku → `NormalizedIntent` (heuristic fallback). |
| `retrieve.py`               | TF-IDF top-k over gold examples.                 |
| `author.py`                 | Haiku → `AttentionSpec` (+ Ping short-circuit).  |
| `dry_run.py`                | `Fetcher` registry + per-card preview renderer.  |
| `harness.py`                | Orchestrator with stage timings.                 |
| `cli.py`                    | `python -m donna.attention.cli "<intent>"`.      |

## Bare-reminder short-circuit

Intents matching `remind me…`, `ping me…`, `don't let me forget…` skip the
LLM authoring call and produce a `card=ping` spec directly — cheapest path
for the most common Attention.

## Shadow mode (design, runtime TBD)

Attentions inferred from user behaviour run in `status=shadow` for up to
`shadow_state.max_ticks` ticks; `spec.promotion_criteria` gates promotion to
`status=offered` (surfaced via WhatsApp). Accept → `live`, ignore →
`quietly_archived`, reject → `rejected`. Spec and runtime record already
support this; a trigger evaluator hook and shadow scheduler are the next
implementation step.

## Stubbed vs live sources

| Source                | Status     | Notes                                          |
|-----------------------|------------|------------------------------------------------|
| `calendar_events`     | **live**   | via `backend/memory/tools/list_calendar.py`.   |
| `user_elicitation`    | **live**   | synthesized from spec params.                  |
| everything else       | stub       | reads `tests/fixtures/<source_type>.json`.     |

## Extending

**Add a source:** register a `_ParamsBase` subclass in `vocabulary.py`, map it
in `SOURCE_PARAMS_MODELS`, drop a fixture in `tests/fixtures/<type>.json`,
optionally register a live `Fetcher` in `dry_run.py::_REGISTRY`.

**Add a gold example:** append a `GoldExample` in `examples/gold_specs.py`
with 3+ paraphrases, a valid spec, and a short rationale.
