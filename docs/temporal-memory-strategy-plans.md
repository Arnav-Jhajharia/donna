# Temporal Memory Strategy Plans

Goal: find the simplest memory strategy that makes Donna understand the user's
status across time:

- what happened last week
- what is happening this week
- what is coming next week
- what is unresolved
- what matters right now

Bias: prefer the simplest implementation that produces a strong situational
brief. Avoid complex machinery unless evals prove it is needed.

## Shared Baseline

All strategies should preserve timestamped memory. Every stored memory-like
event should carry enough temporal metadata to support weekly reasoning:

```json
{
  "user_id": "...",
  "event_time": "...",
  "observed_at": "...",
  "valid_from": "...",
  "valid_to": null,
  "source": "chat | observation | calendar | graph | document | tool",
  "kind": "fact | episode | observation | open_loop | project | person | calendar | decision",
  "entity_refs": ["luca", "antler_deck"],
  "summary": "...",
  "raw_text": "...",
  "confidence": 0.0,
  "salience": 0.0,
  "time_bucket": "today | this_week | last_week | next_week | older_active",
  "metadata": {}
}
```

Minimum viable version: do not create a new universal event table yet. First
use existing timestamps in `chat_messages`, `observations`, `open_loops`,
`calendar_entries`, Supermemory metadata, and Graphiti facts.

## Plan 1: Retrieval-Heavy Temporal Recall

**Position on spectrum:** save less interpretation, retrieve more.

### Idea

Store raw memory well, then let Donna call tools aggressively when she needs
context.

### Writes

- Save chat turns to Postgres and Supermemory.
- Save graph-worthy relationships into Graphiti.
- Save observations and open loops as structured rows.
- Keep `living_profile` light.

### Reads

Donna frequently calls:

- `smart_recall`
- `recall_episodic`
- `recall_graph`
- `list_observations`
- `list_open_loops`
- `list_calendar`

### Graphiti Experiment

Store only high-signal relationships and decisions:

- `user -> working_on -> project`
- `person -> advised -> decision`
- `project -> has_status -> status`

### Supermemory Experiment

Store turn episodes with richer metadata:

- `event_time`
- `time_bucket`
- `entities`
- `project`
- `emotion`
- `salience`

### Evaluation

Ask:

- Did Donna choose the right tool?
- Did retrieved evidence answer the question?
- Did tool calls feel excessive?

### Complexity

Low implementation complexity, higher runtime complexity.

### Verdict

Good baseline, but likely too tool-dependent to feel like Donna already knows.

## Plan 2: Balanced Temporal Brief + Tools

**Position on spectrum:** medium saving, medium retrieval.

### Idea

Build a compact temporal brief from existing memory, then use tools only for
details.

### Writes

Same as Plan 1, plus maintain a small `living_profile` temporal section:

```json
{
  "last_week": [],
  "this_week": [],
  "next_week": [],
  "active_people": [],
  "active_projects": [],
  "open_loops": []
}
```

### Reads

Pre-turn context renders:

1. temporal brief
2. reply/URL context
3. small tracker/open-loop snapshot

Donna calls tools only when the user asks for detail or the brief is missing
something.

### Graphiti Experiment

Use Graphiti mainly for active people, projects, decisions, and relationships.

### Supermemory Experiment

Use Supermemory for episode evidence behind the brief. Query it by week:

- `last week <project>`
- `this week <person>`
- `next week <event>`

### Evaluation

Ask:

- Can Donna answer “what is happening this week?” without retrieval?
- Can Donna drill down when asked “why?”
- Does the brief stay compact?

### Complexity

Moderate. This is probably the simplest useful situational-awareness path.

### Verdict

Strong candidate for v1. Simpler than a full compiler, better than tool-only
recall.

## Plan 3: Nightly Temporal Situation Model

**Position on spectrum:** higher saving, moderate retrieval.

### Idea

Upgrade nightly synthesis into the main mental-model builder.

Nightly synthesis should produce:

```json
{
  "last_week": {
    "summary": "...",
    "changed": [],
    "carried_over": []
  },
  "this_week": {
    "current_status": "...",
    "active_projects": [],
    "active_people": [],
    "risks": [],
    "open_loops": []
  },
  "next_week": {
    "known_events": [],
    "prep_needed": [],
    "likely_followups": []
  },
  "response_policy": {
    "tone_bias": "...",
    "tool_bias": "...",
    "avoid": []
  }
}
```

### Writes

Nightly job reads existing stores and writes the model to
`users.living_profile`.

Inputs:

- recent chat
- Supermemory episodes
- Graphiti facts
- observations
- open loops
- calendar
- user facts
- procedural rules

### Reads

Pre-turn context trusts `users.living_profile` first. Tools are for specifics,
evidence, disputes, or quantitative questions.

### Graphiti Experiment

Graphiti powers the active people/project/decision spine.

### Supermemory Experiment

Supermemory provides source episodes. Store source memory IDs where practical,
but do not overbuild evidence tracking in v1.

### Evaluation

Ask:

- Does the morning brief correctly describe last week, this week, and next week?
- Does Donna avoid stale or irrelevant memories?
- Does the profile reduce tool calls?

### Complexity

Moderate to high. Still manageable if implemented inside the existing
`living_profile.py` instead of creating a new subsystem.

### Verdict

Best serious direction, but should start simple. First improve the existing
nightly synthesis rather than adding a large new architecture.

## Plan 4: Nightly Model + Lightweight Post-Turn Patches

**Position on spectrum:** high saving, low-to-medium retrieval.

### Idea

Nightly builds the situation model. Important turns patch it immediately during
the day.

### Writes

Use Plan 3 nightly synthesis, plus lightweight updates after high-signal turns.

Patch only obvious fields:

- `current_status`
- `active_projects`
- `active_people`
- `open_loops`
- `risks`
- `watch_for_tomorrow`

Do not patch for every turn.

Examples:

- `coffee was 6 bucks` -> observation only
- `antler moved to friday` -> patch upcoming pressure/event
- `deck still feels flat` -> patch active project risk
- `i think i want to quit` -> patch emotional temperature/risk

### Reads

Pre-turn context uses the patched situation model first. Tools are used for
detail.

### Graphiti Experiment

Only write high-signal status changes to Graphiti:

- project status
- people dynamics
- decisions
- major emotional state shifts

### Supermemory Experiment

Store all episodes, but mark important ones with high `salience`.

### Evaluation

Ask:

- After a major user update, does the next reply reflect it immediately?
- Are we over-patching trivial turns?
- Does the model remain coherent by end of day?

### Complexity

High if overbuilt. Reasonable if patching is rule-gated and limited to a few
fields.

### Verdict

Likely best eventual Donna behavior, but probably not the first thing to build.
Do Plan 3 first, then add only the simplest patching gate.

## Plan 5: Compiled Donna State, Minimal Retrieval

**Position on spectrum:** save/synthesize heavily, retrieve rarely.

### Idea

Maintain a denormalized full Donna state object that the runtime mostly trusts.

### Writes

Continuously compile:

```json
{
  "identity": {},
  "current_status": {},
  "temporal_model": {},
  "active_projects": {},
  "active_people": {},
  "open_loops": {},
  "routines": {},
  "risks": {},
  "response_policy": {},
  "evidence_refs": {}
}
```

### Reads

Pre-turn prompt reads compiled Donna state. Tools are only for exact evidence,
numbers, corrections, or disputes.

### Graphiti Experiment

Graphiti feeds the compiler, not the runtime.

### Supermemory Experiment

Supermemory becomes the evidence archive.

### Evaluation

Ask:

- Can Donna answer current-status questions without retrieval?
- Is the compiled model correct?
- How often does it become stale or overconfident?

### Complexity

Very high. Easy to create a confident but wrong Donna.

### Verdict

Not recommended now. This is the dream-state architecture after we have evals.

## Recommended Review Order

Start simple:

1. **Plan 2**: Balanced temporal brief using existing memory.
2. **Plan 3**: Better nightly situation model in `living_profile.py`.
3. **Plan 4**: Add lightweight post-turn patches only if nightly staleness is
   obvious.
4. Keep **Plan 1** as the baseline.
5. Avoid **Plan 5** until evals show the compiler is reliable.

## Testbed

Create a fixed user-history dataset with:

- 30 days chat
- 14 days observations
- open loops
- calendar next 14 days
- graph facts
- Supermemory episodes

Scenarios:

1. `what was happening last week?`
2. `what is my status this week?`
3. `what is coming next week?`
4. `what am i forgetting?`
5. `was i nervous before the last pitch too?`
6. `should i lead with HARP or market size?`
7. `how much coffee this week?`
8. `what changed with luca?`
9. `why do you think i'm stressed?`
10. `no, that's old, antler moved to friday`

Score each strategy:

```text
0 = wrong or hallucinated
1 = partially relevant
2 = correct but clumsy
3 = correct and context-aware
4 = feels like Donna already knew
```

Also track:

- tool count
- latency
- token cost
- stale-memory failures
- missed-memory failures
- irrelevant-memory surfacing

## Practical Recommendation

Build **Plan 2 first**, not Plan 5.

The minimum useful implementation is:

```text
existing stores
-> simple temporal brief
-> render in pre-turn context
-> tools only for drilldown
```

If that feels too shallow, upgrade the existing nightly synthesis into Plan 3.
Only add Plan 4 patching after real traces show that nightly staleness is a
problem.
