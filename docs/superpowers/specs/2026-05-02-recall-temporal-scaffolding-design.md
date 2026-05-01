# Recall temporal scaffolding

Date: 2026-05-02
Status: design — pending implementation plan
Owner: arnav

## Problem

The `recall` tool feeds the BRAIN a flat, source-blind, time-blind list. Three drift points cause this:

1. **`smart_recall` strips `metadata`.** `backend/memory/tools/smart_recall.py` serializes each `RetrievalResult` into `{id, source, content, score, rerank_score}` and discards `metadata` — which is exactly where `event_time`, `valid_at`, `created_at`, `updated_at`, `generated_at` live.
2. **`_render_dict_item` only reads four keys.** `donna_runtime/tools.py:88-93` formats each hit as `{source}: {content}` by looking up `content` / `fact` / `rule` / `title`. Even payloads that already carry timestamps (observations, open_loops) lose them at render time.
3. **No grouping, no header, no span.** The brain sees one flat bulleted list. It cannot reason about staleness, recency, or whether two hits describe the same moment.

Net effect: the BRAIN, which is responsible for cohesion, has no temporal axis to reason on. Donna's replies read as list-dumps because she's been handed list-shaped data.

## Goals

- Every recalled item carries a local timestamp + a relative-time label (e.g. `2d ago`) when its source has temporal data.
- Recall output is grouped by source, with a header line summarizing count and span.
- Renderer is deterministic. No new LLM calls. The single tool-use loop is preserved.
- The brain (Sonnet 4.6) does the cohesion. Recall's job is to give it a temporally scaffolded substrate.

## Non-goals

- LLM-synthesized cohesive paragraph inside `recall`. Rejected: Haiku has strictly less context than the brain (no USER MODEL, no SITUATION BRIEF, no RECENT CHAT) and would produce a degraded version of what the brain would say. Also violates "single tool-use loop" + cost discipline in `CLAUDE.md`.
- Changing `RetrievalResult` DTO. It already carries `metadata`.
- Folding calendar / document chunks / procedural rules / bitemporal facts into the unified fanout. Separate roadmap item per `CLAUDE.md` "Memory layers" section.
- Reworking `read_situation_brief` payload shape. It is already structured.
- System-prompt changes. Reassess only if regressions show up.

## Architecture

Three layers, smallest fix first.

### Layer 1 — `smart_recall`: stop stripping metadata

**File:** `backend/memory/tools/smart_recall.py`

Include `metadata` in the per-result dict so downstream renderers can see timestamps:

```python
return ok(
    [
        {
            "id": r.id,
            "source": r.source,
            "content": r.content,
            "score": r.score,
            "rerank_score": r.rerank_score,
            "metadata": r.metadata or {},
        }
        for r in results
    ]
)
```

That is the entire change at this layer.

### Layer 2 — Time normalization helper

**New file:** `backend/memory/retrieval/temporal.py`

Single source-aware extractor that produces a canonical `ResultTime` from any recall hit, plus a relative-time formatter.

```python
@dataclass(frozen=True)
class ResultTime:
    iso_utc: str           # e.g. 2026-04-29T19:14:00+00:00
    local_label: str       # e.g. "apr 29, 19:14"
    relative_label: str    # e.g. "2d ago", "in 3h", "just now"
    epoch: float           # for sorting

def extract_event_time(
    *,
    source: str,
    metadata: dict,
    timezone_name: str | None,
    now: datetime | None = None,
) -> ResultTime | None: ...
```

**Source → field mapping:**

| Source            | Primary field             | Fallback                  | Notes |
|-------------------|---------------------------|---------------------------|-------|
| `observations`    | `metadata.event_time`     | —                         | already ISO in fanout |
| `open_loops`      | `metadata.created_at`     | —                         | already ISO in fanout |
| `graphiti`        | `metadata.valid_at`       | `metadata.created_at`     | bitemporal — prefer `valid_at` |
| `supermemory`     | `metadata.updated_at`     | —                         | reflects index time, not event time — comment in code |
| `documents`       | `metadata.updated_at`     | —                         | may be `None`; that is fine |
| `situation_brief` | `metadata.generated_at`   | —                         | rendered as header |
| anything else     | —                         | —                         | returns `None` |

Returns `None` cleanly when the field is missing or unparseable. Never raises.

**Relative-label rules** (using the user's local timezone for day-boundary math; UTC fallback when timezone is unset):

| Delta                | Label                  |
|----------------------|------------------------|
| `< 60s` past or future | `just now`           |
| `60s – 60min`        | `Nm ago` / `in Nm`     |
| `1h – 24h`           | `Nh ago` / `in Nh`     |
| `1d – 7d`            | `Nd ago` / `in Nd`     |
| `7d – 365d`          | `mmm d` (no relative)  |
| `> 365d`             | `mmm d yyyy`           |

Day boundaries respect local time, so "yesterday" wraps correctly per user. Reuses existing helpers `format_local` and `timezone_label` from `backend.memory.time` for `local_label`.

### Layer 3 — Recall-specific renderer

**File:** `donna_runtime/tools.py` (new helper, sibling to `_render_payload`)

```python
def _render_recall_payload(
    payload: list[dict],
    *,
    timezone_name: str | None,
    source_hint: str | None = None,
) -> str: ...
```

Behavior:

1. **Hydrate `source` per item.** When `source_hint` is given (non-auto branches: `purpose=observations|open_loops|situation_brief`) use it for items missing a `source` key. Otherwise use the item's own `source`.
2. **Compute `ResultTime` per item** via `extract_event_time`.
3. **Group by source** in fixed priority order:
   `situation_brief` → `open_loops` → `observations` → `graphiti` → `supermemory` → `documents` → `unknown`.
4. **Sort within group** by `ResultTime.epoch` desc; items with `None` time go last and retain their incoming (rerank) order.
5. **Header line** (only when at least one item has a timestamp):
   `recall: N hits across K sources, span <oldest_local> → <newest_local>`
   When no items have timestamps: `recall: N hits across K sources`.
6. **Per-group blocks:**
   ```
   observations (3):
   - 2d ago (apr 29, 19:14): expense amount=420 INR raw=auto
   - 4d ago (apr 27, 12:00): meal calories=750 raw=salad
   - 6d ago (apr 25, 22:01): mood score=4
   ```
   When a row has no time: omit the relative tag and the parenthetical, keep the colon and the body.
7. **Per-group cap = 6 rows.** When truncated, append:
   `(showing 6 of N — narrow with type/period)`
8. **`situation_brief` block** is special:
   ```
   situation_brief (as of apr 30, 06:00):
   - current_status: ...
   - this_week: ...
   ```
   Header line replaces the per-row time.
9. **Item body** is whichever of `content` / `fact` / `rule` / `title` exists, falling back to a compact `key=val` rendering of the item dict minus `id` / `source` / `metadata` / `score` / `rerank_score`.
10. **Observation content de-dup.** Today `fanout._render_observation_row` bakes `at {when}` into the `content` string. With the renderer now owning time, that becomes a duplicate ("2d ago (apr 29, 19:14): expense observation at apr 29, 19:14: ..."). Fix: drop the `at {when}` clause from `_render_observation_row` in `backend/memory/retrieval/fanout.py` so content reads `"{type} observation: {fields}{raw}"`. Same change to `_render_observation_summary` for the aggregate row.

**Wiring:**

- `recall` wrapper at `donna_runtime/tools.py:862` calls `_render_recall_payload` for every branch:
  - `purpose=auto` → `source_hint=None`, payload is the list from `smart_recall` (already in `{source, content, metadata, ...}` shape after Layer 1).
  - `purpose=observations|tracker` → `source_hint="observations"`, payload from `list_observations`.
  - `purpose=open_loops|loops` → `source_hint="open_loops"`, payload from `list_open_loops`.
  - `purpose=situation_brief|brief` → `source_hint="situation_brief"`, payload from `read_situation_brief` (a single dict, wrapped into a one-item list before render).
- **Payload normalization.** `list_observations` and `list_open_loops` return items with timestamp fields at the top level (`event_time`, `created_at`) rather than under `metadata`. Inside `_render_recall_payload`, normalize each item to `{source, content, metadata}` shape before passing to `extract_event_time`:
  - For observations: `metadata = {"event_time": item["event_time"], "type": item["type"], "fields": item.get("fields"), ...}`; `content` synthesized from type + fields + raw.
  - For open_loops: `metadata = {"created_at": item["created_at"], "status": item["status"]}`; `content` from `item["content"]`.
  - For situation_brief: dict is rendered via the special block (header + bullet lines), no normalization needed.
- Other tools keep `_render_payload`. The recall renderer is recall-only.
- Resolving `timezone_name`: read it from the user row once at the top of `recall()` (single async query) and thread through. Keep the cost cheap; do not refetch per item.

## Data flow

```
brain
  └── recall(query [, purpose, observation_type, period])
        ├── load user.timezone (one query)
        ├── route by purpose
        │     ├── auto              → smart_recall  (metadata intact)
        │     ├── observations      → list_observations
        │     ├── open_loops        → list_open_loops
        │     └── situation_brief   → read_situation_brief
        └── _render_recall_payload(payload, timezone_name, source_hint)
              ├── extract_event_time per item
              ├── group by source (fixed priority)
              ├── sort by recency within group (None last)
              ├── emit header (count + span)
              └── emit per-group blocks (capped at 6, with truncation marker)
```

The brain receives a timestamped, grouped, span-summarized list. It synthesizes from there.

## Edge cases

- **No timestamps anywhere** (e.g. all hits are doc chunks with no `updated_at`): header omits the span; rows omit the relative tag. Renders cleanly without warnings.
- **User has no timezone set**: `format_local` falls back to UTC. Relative math is correct in either case (we compare epochs).
- **Stale `supermemory.updated_at`**: this reflects when Donna last indexed the memory, not when the user lived the event. Leave a code comment in `temporal.py` so future readers don't assume event-time semantics. The label is still useful as "Donna last touched this Nd ago."
- **Future timestamps** (e.g. `graphiti.valid_at` in the future): label as `in Nh` / `in Nd`. Cheap to support; trivially symmetric.
- **`situation_brief` has no `generated_at`**: fall back to a generic `situation_brief:` header with no "as of" clause.
- **Item body has unparseable structure**: fall back to `json.dumps(item, default=str, sort_keys=True)` (mirrors current `_render_dict_item` behavior).
- **Empty payload after route** (`status == "no_hits"`): existing `_tool_text` no-hits path is preserved. The renderer is only invoked on `ok` payloads.

## Tests

New test files:

- `tests/test_recall_temporal.py`
  - `extract_event_time` happy path for each source (`observations`, `open_loops`, `graphiti` valid-at + fallback, `supermemory`, `documents`, `situation_brief`).
  - `extract_event_time` returns `None` when the relevant metadata field is missing or unparseable.
  - `relative_label` boundary cases: `< 60s`, `5m`, `2h`, `2d`, `8d`, `400d`, future deltas (`in 3h`, `in 2d`).
  - Day-boundary correctness: a UTC time that is "today" in UTC but "yesterday" in IST renders as `1d ago` for an IST user.
- `tests/test_recall_render.py`
  - Synthetic mixed-source payload with hand-picked timestamps. Snapshot the rendered string. Assertions:
    - header line present, mentions count + span
    - groups appear in priority order
    - within group, ordered by recency desc
    - per-group cap honored (truncation marker present when N > 6)
    - `situation_brief` renders with `as of` header
    - rows without timestamps render without the relative tag and parenthetical
- Extend the existing recall integration test (or `tests/test_integration_end_to_end.py` if recall has no dedicated integration suite) to assert the rendered output contains at least one `d ago` token when seed data spans days.

Coverage target: ≥ 80% on new helpers per `~/.claude/rules/python/testing.md`. Tests precede implementation per the same rules' TDD section.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Token bloat | ~15 extra chars per line × ~12 hits ≈ 200 extra tokens per recall. Acceptable against the per-turn cost budget. Per-group cap of 6 prevents fanout from blowing up the line count. |
| Scope creep into fanout sources | Explicit non-goal. New sources stay out of this change. |
| Prompt drift | No system-prompt change in this design. Add a single line to `donna_runtime/prompt.py` only if observed regressions show the brain misreading the new shape. |
| Stale `updated_at` semantics on supermemory misleading the brain | Code comment + relative-label phrasing keeps the meaning honest ("last touched") rather than implying "happened then." |
| Per-turn timezone lookup cost | One async query per recall call. Negligible. |

## Out-of-scope (deferred)

- Folding calendar / procedural-rules / bitemporal-facts / document-chunks-as-first-class into the unified fanout. Tracked via existing roadmap item.
- LLM synthesis layer over recall.
- Cross-source dedupe based on temporal proximity (e.g. graphiti fact + observation describing the same dinner).
- Sparkline / histogram view of observation density over time.

## Acceptance

A reactive turn where the user asks "what's been going on with maya" produces, inside the BRAIN's tool result, a recall payload that:

- has a header line including a span,
- shows hits grouped by source in priority order,
- shows each row with a relative time label and a local timestamp,
- caps each group at 6 with a truncation marker if needed.

Donna's reply, drafted by the BRAIN unchanged, reads as a temporally cohesive paragraph rather than a list-dump.
