from __future__ import annotations

from claude_agent_sdk import tool

from backend.memory.user_facts.schema import FactKey

from ..hooks import _CURRENT_USER_ID, _fire_memory_hooks
from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id, _result_text, _tool_text

_FACT_KEY_VALUES: tuple[str, ...] = tuple(k.value for k in FactKey)
_FACT_KEY_DESCRIPTION = (
    "Canonical fact key when kind is fact/preference. Must be one of: "
    + ", ".join(_FACT_KEY_VALUES)
    + ". Use preferred_name for what the user wants to be called."
)

@tool(
    "log_observation",
    "Record a countable user event. `type` is the category (expense, meal, mood, "
    "sleep, habit, exercise, symptom). `fields` is the numeric/structured payload "
    "('amount_usd': 6 for an expense, 'hours': 7 for sleep, 'score': 4 for mood 1-5). "
    "Include `event_time` as an ISO timestamp when the event happened earlier than "
    "this message ('coffee was 6 bucks this morning' -> event_time = this morning). "
    "Do NOT use for feelings, intentions, decisions, commitments, or vague statements "
    "('i feel tired', 'thinking about quitting') — those are open_loops or memory, "
    "not observations. Do NOT invent a number the user did not state. Do NOT use for "
    "the same event twice within a turn.",
    {
        "type": "object",
        "required": ["type", "fields"],
        "properties": {
            "type": {"type": "string"},
            "fields": {"type": "object"},
            "tags": {"type": "object"},
            "raw": {"type": "string"},
            "event_time": {
                "type": "string",
                "description": "Optional ISO timestamp for when the event happened.",
            },
            "confidence": {"type": "number"},
        },
    },
)
@traceable(name="donna.tool.log_observation", run_type="tool")
async def log_observation(args):
    from backend.memory.tools.log_observation import log_observation as _log_observation

    user_id = _current_user_id()
    obs_type = str(args.get("type") or "").strip()
    fields = args.get("fields") if isinstance(args.get("fields"), dict) else {}
    if not user_id or not obs_type or not fields:
        return text_content("Observation not logged.")
    res = await _log_observation(
        user_id=user_id,
        type=obs_type,
        fields=fields,
        tags=args.get("tags") if isinstance(args.get("tags"), dict) else {},
        raw=str(args.get("raw") or ""),
        event_time=str(args.get("event_time") or ""),
        confidence=float(args.get("confidence") or 1.0),
    )

    # Best-effort: hand the freshly-written row to the observation
    # spawner. Never block the original tool's reply on spawner failure.
    try:
        obs_id = _extract_observation_id(res)
        if obs_id:
            await _spawn_from_observation(
                user_id=user_id,
                obs_id=obs_id,
                obs_type=obs_type,
                fields=fields,
                raw=str(args.get("raw") or ""),
                event_time=str(args.get("event_time") or ""),
            )
    except Exception:
        logger.exception("log_observation: spawner hook raised")

    return _tool_text(res, no_hits_text="Observation not logged.", degraded_text="Observation unavailable.")


def _extract_observation_id(res: Any) -> str | None:
    """Pull the observation id out of the ToolResult shape ({status, payload})."""
    if not isinstance(res, dict):
        return None
    if res.get("status") != "ok":
        return None
    payload = res.get("payload")
    if isinstance(payload, dict):
        return payload.get("id")
    return None


async def _spawn_from_observation(
    *,
    user_id: str,
    obs_id: str,
    obs_type: str,
    fields: dict,
    raw: str,
    event_time: str,
) -> None:
    """Fetch the persisted Observation row and feed the spawner.

    Done in a fresh session so the spawner sees the committed event_time
    + enriched fields rather than relying on the in-process tool args.
    """
    try:
        from sqlalchemy import select

        from backend.db.models import Observation
        from backend.db.session import async_session
    except Exception:
        return
    obs_row = None
    try:
        async with async_session() as session:
            obs_row = (
                await session.execute(
                    select(Observation).where(Observation.id == obs_id)
                )
            ).scalar_one_or_none()
    except Exception:
        logger.exception("log_observation: spawner row fetch failed id=%s", obs_id)
    if obs_row is None:
        return
    from proactive.spawners import observation as observation_spawner

    await observation_spawner.maybe_spawn(obs_row, user_id)

@tool(
    "track_open_loop",
    "Record an unresolved thread or commitment. Use when the user leaves a "
    "follow-up, decision, or obligation hanging. "
    "Do NOT use for timed reminders (use schedule_reminder) or for completed "
    "facts (use log_observation).",
    {
        "type": "object",
        "required": ["content"],
        "properties": {
            "content": {"type": "string"},
            "source_message": {"type": "string"},
        },
    },
)
@traceable(name="donna.tool.track_open_loop", run_type="tool")
async def track_open_loop(args):
    from backend.memory.tools.track_open_loop import track_open_loop as _track_open_loop

    user_id = _current_user_id()
    content = str(args.get("content") or "").strip()
    if not user_id or not content:
        return text_content("Open loop not tracked.")
    res = await _track_open_loop(
        user_id=user_id,
        content=content,
        source_message=str(args.get("source_message") or ""),
    )
    return _tool_text(res, no_hits_text="Open loop not tracked.", degraded_text="Open loops unavailable.")


@tool(
    "close_open_loop",
    "Mark a prior open loop resolved. Use a loop id from list_open_loops. "
    "Do NOT use without a loop_id or on a loop the user has not confirmed resolved.",
    {
        "type": "object",
        "required": ["loop_id"],
        "properties": {"loop_id": {"type": "string"}},
    },
)
@traceable(name="donna.tool.close_open_loop", run_type="tool")
async def close_open_loop(args):
    from backend.memory.tools.close_open_loop import close_open_loop as _close_open_loop

    user_id = _current_user_id()
    loop_id = str(args.get("loop_id") or "").strip()
    if not user_id or not loop_id:
        return text_content("Open loop not closed.")
    res = await _close_open_loop(user_id=user_id, loop_id=loop_id)
    return _tool_text(res, no_hits_text="Open loop not found.", degraded_text="Open loops unavailable.")


@tool(
    "clear_pending_note",
    "Dismiss a queued proactive note from the PENDING NOTES block. Use "
    "when this turn's send_burst already addresses what the note was "
    "queued for (reason='delivered'), when the note is no longer worth "
    "surfacing (reason='irrelevant'), or when the user brought up the "
    "topic themselves first (reason='superseded_by_user'). Do NOT use "
    "for notes you have not actually consumed in this turn — the brain "
    "is the only consumer of pending notes, and silently clearing is "
    "indistinguishable from forgetting.",
    {
        "type": "object",
        "required": ["note_id"],
        "properties": {
            "note_id": {"type": "string"},
            "reason": {
                "type": "string",
                "enum": ["delivered", "irrelevant", "superseded_by_user"],
                "description": "Default: delivered.",
            },
        },
    },
)
@traceable(name="donna.tool.clear_pending_note", run_type="tool")
async def clear_pending_note(args):
    from proactive.dispatcher import clear_pending_note as _clear

    note_id = str(args.get("note_id") or "").strip()
    reason = str(args.get("reason") or "delivered").strip() or "delivered"
    if not note_id:
        return text_content("clear_pending_note: note_id is required.")
    ok = await _clear(note_id, reason=reason)
    if ok:
        return text_content(f"Pending note {note_id} cleared as {reason}.")
    return text_content(
        f"Pending note {note_id} not cleared (already resolved or unknown id)."
    )


@tool(
    "set_timezone",
    "Set the user's timezone. `timezone` MUST be a valid IANA string "
    "('Asia/Singapore', 'America/New_York', 'Europe/London') — never an "
    "abbreviation ('PST', 'IST') or UTC offset ('+05:30'). Use only when the "
    "user explicitly confirms or corrects their timezone. Do NOT use on a "
    "passing location reference ('i'm in tokyo this week' ≠ timezone change), "
    "on a guess, or when the timezone check in runtime context already shows "
    "confirmed=true.",
    {
        "type": "object",
        "required": ["timezone"],
        "properties": {
            "timezone": {"type": "string"},
            "source": {"type": "string", "description": "Optional provenance label (default: user_correction)."},
        },
    },
)
@traceable(name="donna.tool.set_timezone", run_type="tool")
async def set_timezone(args):
    from backend.memory.tools.set_timezone import set_timezone as _set_timezone

    user_id = _current_user_id()
    tz = str(args.get("timezone") or "").strip()
    if not user_id:
        return text_content(
            "Timezone not updated: no user_id in scope. Runtime bug — report it."
        )
    if not tz:
        return text_content(
            "Timezone not updated: 'timezone' is required. Pass an IANA name like "
            "'Asia/Singapore', 'America/New_York', or 'Europe/London' — never an "
            "abbreviation ('PST', 'IST') or UTC offset ('+05:30')."
        )
    res = await _set_timezone(
        user_id=user_id,
        timezone=tz,
        source=str(args.get("source") or "user_correction"),
    )
    return _tool_text(res, no_hits_text="Timezone not updated.", degraded_text="Timezone unavailable.")


@tool(
    "resolve_time_expression",
    (
        "Resolve a natural-language time expression ('last tuesday', "
        "'3 hours ago', 'tomorrow at 6pm') to a concrete UTC ISO timestamp "
        "anchored in the user's timezone. Use before filtering bi-temporal "
        "facts by t_valid or before scheduling. "
        "Do NOT use for ISO timestamps the user already gave, for vague "
        "durations like 'a few days' (ask the user), or when no time "
        "dimension is present."
    ),
    {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {"type": "string"},
            "now": {
                "type": "string",
                "description": "Optional ISO anchor for 'now' (testing only).",
            },
        },
    },
)
@traceable(name="donna.tool.resolve_time_expression", run_type="tool")
async def resolve_time_expression(args):
    from backend.memory.tools.resolve_time_expression import (
        resolve_time_expression as _resolve,
    )

    user_id = _current_user_id()
    expression = str(args.get("expression") or "").strip()
    if not user_id or not expression:
        return text_content("Could not resolve time expression.")
    res = await _resolve(
        user_id=user_id,
        expression=expression,
        now=args.get("now") or None,
    )
    return _tool_text(
        res,
        no_hits_text="Could not resolve time expression.",
        degraded_text="Could not resolve time expression.",
    )


@tool(
    "remember",
    (
        "Record a user-stated observation, commitment, or timezone into memory. "
        "This wrapper routes to the right backend. Bias toward using it when "
        "the current user message gives information Donna should hold onto. "
        "For kind='observation': always pass observation_type. Pass fields when "
        "the event has obvious numeric/structured data — expense {amount_usd: 6}, "
        "meal {item, calories}, sleep {hours: 7}, mood {score: 4}, exercise "
        "{minutes, type}, alcohol {count, unit}. For casual observations with no "
        "natural numeric shape (notes, social events, ambient feelings), "
        "fields may be empty {} — the `content` text captures the meaning. "
        "For kind='commitment': use when the user states they will do something "
        "with no clock attached (\"i'll send the doc\", \"need to call mom\"). "
        "When a clock is named (\"by friday\", \"tonight\", \"in an hour\"), "
        "use attend() instead. Resolution is detected automatically from chat. "
        "Profile facts (name, city, profession, age, etc.) are handled "
        "automatically by a pre-turn detector and the post-turn extractor — "
        "do NOT call this with kind='fact' or kind='preference'. Those kinds "
        "are removed. The legacy kinds 'open_loop' and 'loop_closed' are also "
        "removed — use 'commitment' instead, and never try to close one. "
        "Do NOT call this to re-save things that only came from USER MODEL, "
        "SITUATION BRIEF, runtime context, or a recall result. "
        "Do NOT invent values the user did not state (no fabricated amounts, "
        "timezones). "
        "Do NOT use for timed reminders (use schedule) or for things better "
        "surfaced as a dashboard attention (use watch). "
        "Do NOT call twice for the same observation/commitment/timezone within one turn."
    ),
    {
        "type": "object",
        "required": ["kind", "content"],
        "properties": {
            "kind": {
                "type": "string",
                "description": "observation, commitment, or timezone.",
            },
            "content": {"type": "string"},
            "observation_type": {"type": "string"},
            "fields": {"type": "object"},
            "tags": {"type": "object"},
            "event_time": {"type": "string"},
            "timezone": {"type": "string"},
            "confidence": {"type": "string", "description": "low, medium, or high."},
        },
    },
)
@traceable(name="donna.tool.remember", run_type="tool")
async def remember(args):
    user_id = _current_user_id()
    kind = str(args.get("kind") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    if not user_id:
        return text_content(
            "Memory not recorded: no user_id in scope. This is a runtime bug, "
            "not a tool-call error — report it and move on."
        )
    if not kind:
        return text_content(
            "Memory not recorded: 'kind' is required. Valid kinds: "
            + ", ".join(["observation", "commitment", "timezone"])
            + "."
        )
    if kind in {"fact", "preference"}:
        return text_content(
            "Memory not recorded: kind='fact' and kind='preference' have been "
            "removed from remember. Profile facts (name, city, profession, etc.) "
            "are written automatically by the pre-turn detector and post-turn "
            "extractor when the user states them. Drop the tool call; just reply."
        )
    if not content:
        return text_content(
            f"Memory not recorded: 'content' is required (got empty string). "
            f"For kind={kind!r}, pass the user-stated fact/commitment/value."
        )

    if kind == "observation":
        from backend.memory.tools.log_observation import log_observation as _log_observation

        obs_type = str(args.get("observation_type") or "").strip()
        fields = args.get("fields") if isinstance(args.get("fields"), dict) else {}
        if not obs_type:
            return text_content(
                "OBSERVATION REJECTED. 'observation_type' is required. Do NOT "
                "claim it was logged. Common types: expense, meal, mood, sleep, "
                "habit, exercise, symptom, alcohol, note. Example: "
                "observation_type='alcohol', fields={'count': 5, 'unit': 'beers'}."
            )
        # Casual observations (alcohol, social events, notes) often have no
        # obvious numeric `fields`. We accept empty `fields` — the `raw`
        # text carries the meaning, and pattern miners still count by type.
        # Structured types (expense, meal, sleep) should still pass fields,
        # but the tool description handles that nudge; we don't reject here.
        res = await _log_observation(
            user_id=user_id,
            type=obs_type,
            fields=fields,
            tags=args.get("tags") if isinstance(args.get("tags"), dict) else {},
            raw=content,
            event_time=str(args.get("event_time") or ""),
            confidence=_numeric_confidence(args.get("confidence")),
        )
        return _result_text(
            "remembered observation",
            res,
            no_hits_text=(
                "OBSERVATION NOT RECORDED. Do NOT claim you logged it. "
                "Note the user without saying 'logged'."
            ),
            degraded_text=(
                "OBSERVATION FAILED (backend error). Do NOT claim you logged "
                "it. Acknowledge the user without saying 'logged'."
            ),
        )

    if kind in {"open_loop", "commitment"}:
        # open_loops as a separate concept is being retired — the table
        # was write-only in practice (close_open_loop never got called by
        # the brain). Both kinds now land as observations of type
        # 'commitment' so the LP synthesizer can surface unresolved ones
        # and the post-turn extractor can detect resolution mentions.
        from backend.memory.tools.log_observation import log_observation as _log_observation

        tags = args.get("tags") if isinstance(args.get("tags"), dict) else {}
        tags = {**tags, "source": "stated", "resolved": False}
        res = await _log_observation(
            user_id=user_id,
            type="commitment",
            fields={"text": content},
            tags=tags,
            raw=content,
            event_time=args.get("event_time"),
            confidence=_numeric_confidence(args.get("confidence")),
        )
        return _result_text("remembered commitment", res, no_hits_text="Commitment not recorded.")

    if kind == "loop_closed":
        # Resolution detection is moving to the post-turn extractor.
        # Reply degraded so the model doesn't claim it closed something.
        return text_content(
            "Memory not recorded: kind='loop_closed' has been removed. "
            "Resolution of stated commitments is now detected automatically "
            "from chat. Drop the tool call; just reply."
        )

    if kind == "timezone":
        from backend.memory.tools.set_timezone import set_timezone as _set_timezone

        tz = str(args.get("timezone") or content).strip()
        res = await _set_timezone(user_id=user_id, timezone=tz, source="user_correction")
        return _result_text("remembered timezone", res, no_hits_text="Timezone not updated.")

    return text_content(
        f"Memory not recorded: unsupported kind {kind!r}. "
        f"Valid kinds: observation, commitment, timezone."
    )


def _numeric_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    return {"low": 0.4, "medium": 0.7, "high": 1.0}.get(text, 1.0)


def _fact_confidence(value: Any):
    from backend.memory.user_facts.schema import Confidence

    text = str(value or "medium").strip().lower()
    if text in {"low", "medium", "high"}:
        return Confidence(text)
    return Confidence.MEDIUM


@tool(
    "update_identity",
    "Update a persistent identity fact about the user (the USER MODEL). Use this for semi-permanent state, "
    "like a job change, a relationship, a new school, or a core preference. Do NOT use for ephemeral events "
    "(use log_observation). Do NOT use for temporary situations (use track_open_loop).",
    {
        "type": "object",
        "required": ["key", "value"],
        "properties": {
            "key": {"type": "string", "description": _FACT_KEY_DESCRIPTION},
            "value": {"type": "string", "description": "The new value for the identity fact."},
        },
    },
)
@traceable(name="donna.tool.update_identity", run_type="tool")
async def update_identity(args):
    from backend.memory.tools.update_identity import update_identity as _update_identity

    user_id = _current_user_id()
    if not user_id:
        return text_content("Missing user_id.")
    key = str(args.get("key") or "").strip()
    value = str(args.get("value") or "").strip()
    if not key or not value:
        return text_content("Missing key or value.")
    res = await _update_identity(user_id=user_id, key=key, value=value)
    return _tool_text(res)


@tool(
    "gather_context",
    "The unified tool to fetch the user's current state. Use this to instantly pull schedule, pending tasks, "
    "and memory hits in a single network hop. "
    "Use for broad day-map or current-situation questions where multiple context sources matter. "
    "Do NOT use for ambient chatter, greetings with no ask, a single obvious calendar lookup, or a write action.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional search term for fuzzy memory recall."},
            "include_calendar_days": {"type": "integer", "description": "Days ahead to fetch schedule. 0 = none, 1 = today."},
            "include_open_loops": {"type": "boolean", "description": "True to see pending commitments."},
            "include_recent_trackers": {"type": "boolean", "description": "True to see recently logged events (meals, habits, etc)."},
        },
    },
)
@traceable(name="donna.tool.gather_context", run_type="tool")
async def gather_context(args):
    from backend.memory.tools.gather_context import gather_context as _gather_context

    user_id = _current_user_id()
    if not user_id:
        return text_content("Missing user_id.")
    query = args.get("query")
    include_calendar_days = args.get("include_calendar_days", 0)
    include_open_loops = args.get("include_open_loops", False)
    include_recent_trackers = args.get("include_recent_trackers", False)
    res = await _gather_context(
        user_id=user_id,
        query=query,
        include_calendar_days=int(include_calendar_days) if include_calendar_days is not None else 0,
        include_open_loops=bool(include_open_loops),
        include_recent_trackers=bool(include_recent_trackers),
    )
    return _tool_text(res)


