from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from claude_agent_sdk import tool

from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)

_RECURRENCE_PRESETS: tuple[str, ...] = (
    "daily", "weekdays", "weekends", "weekly", "monthly",
)


def _parse_remind_at(raw: str, user_tz: str) -> datetime | None:
    """Parse `at` into a tz-aware UTC datetime.

    Accepts ISO8601 with offset, ISO8601 with trailing 'Z', or naive
    ISO8601 (interpreted in user_tz). Returns None on parse failure.
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(user_tz))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_reminder_cadence(
    *, fire_at_utc: datetime, recurrence: str | None, user_tz: str
) -> Any:
    """Build a Cadence from `at` + optional recurrence preset / cron.

    Preset's hour/minute/dow/day are derived from fire_at_utc projected
    into user_tz so "daily at 12pm" fires at the user's actual 12pm.
    """
    from donna.attention.schema import Cadence
    from donna.attention.vocabulary import CadenceType

    if not recurrence:
        return Cadence(
            type=CadenceType.ONE_SHOT,
            params={"trigger_at": fire_at_utc.isoformat()},
        )

    rec = recurrence.strip().lower()
    local = fire_at_utc.astimezone(ZoneInfo(user_tz))
    minute = local.minute
    hour = local.hour
    cron_dow = (local.weekday() + 1) % 7  # Python Mon=0..Sun=6 → cron Sun=0..Sat=6
    day = local.day

    if rec == "daily":
        return Cadence(type=CadenceType.SCHEDULED, params={"cron": f"{minute} {hour} * * *"})
    if rec == "weekdays":
        return Cadence(type=CadenceType.SCHEDULED, params={"cron": f"{minute} {hour} * * 1-5"})
    if rec == "weekends":
        return Cadence(type=CadenceType.SCHEDULED, params={"cron": f"{minute} {hour} * * 0,6"})
    if rec == "weekly":
        return Cadence(type=CadenceType.SCHEDULED, params={"cron": f"{minute} {hour} * * {cron_dow}"})
    if rec == "monthly":
        return Cadence(type=CadenceType.SCHEDULED, params={"monthly_day": day, "hour": hour, "minute": minute})

    if len(rec.split()) == 5:
        return Cadence(type=CadenceType.SCHEDULED, params={"cron": rec})

    return Cadence(type=CadenceType.ONE_SHOT, params={"trigger_at": fire_at_utc.isoformat()})


@tool(
    "remind",
    (
        "Schedule a one-shot or recurring reminder. SIMPLE primitive — no "
        "card classification, no LLM author, no source resolution: just a "
        "DonnaSchedule row that fires at the given time. The fired message "
        "is composed in Donna's voice at fire time, so `text` is the TOPIC, "
        "not the literal SMS body.\n\n"
        "Use for plain time-bound reminders the user asked for or that you "
        "(origin='donna') want to schedule yourself: 'remind me at 5pm to "
        "call mom', 'every weekday at 9am journal', 'tomorrow noon, packing'. "
        "Always pass `at` as an ISO timestamp resolved by you — call "
        "resolve_time_expression first if the user gave natural language. "
        "If the user only wants ONE fire, leave recurrence empty.\n\n"
        "Do NOT use for: standing watches over a topic ('watch poke "
        "launch' — that is attend with card=event_stream), weekly briefs "
        "('brief me on fundraising' — attend with card=brief), calendar prep "
        "('prep me before sarah 1:1' — attend with card=prep_doc), or "
        "open-ended commitments without a fire time ('text luca' — that is "
        "track_open_loop). When the cadence or sources require LLM judgment, "
        "use `attend`. When you have an exact fire time, use `remind`."
    ),
    {
        "type": "object",
        "required": ["text", "at"],
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "What to remind about, in the user's words. Donna will "
                    "phrase the actual message in her voice at fire time."
                ),
            },
            "at": {
                "type": "string",
                "description": (
                    "ISO8601 timestamp for the first (or only) fire. "
                    "Include timezone offset or trailing Z. "
                    "Call resolve_time_expression first if the user gave "
                    "natural language like 'tomorrow at 9am'."
                ),
            },
            "recurrence": {
                "type": "string",
                "description": (
                    "Optional recurrence. Presets: daily, weekdays, weekends, "
                    "weekly, monthly. Or any 5-field cron expression. "
                    "Leave empty for a one-shot reminder."
                ),
            },
            "origin": {
                "type": "string",
                "enum": ["user", "donna"],
                "description": "'user' when the user asked, 'donna' when you are scheduling proactively.",
            },
        },
    },
)
@traceable(name="donna.tool.remind", run_type="tool")
async def remind(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("Reminder not set: no user_id in scope.")

    text = str(args.get("text") or "").strip()
    at_raw = str(args.get("at") or "").strip()
    recurrence = str(args.get("recurrence") or "").strip() or None
    origin = str(args.get("origin") or "user").strip().lower()
    if origin not in ("user", "donna"):
        origin = "user"

    if not text:
        return text_content("Reminder not set: 'text' is required.")
    if not at_raw:
        return text_content(
            "Reminder not set: 'at' is required. "
            "Call resolve_time_expression first for natural-language times."
        )

    try:
        from backend.memory.user_facts.api import get_user_facts
        facts = await get_user_facts(user_id)
        user_tz = (facts or {}).get("timezone") or "UTC"
    except Exception:
        user_tz = "UTC"

    fire_at_utc = _parse_remind_at(at_raw, user_tz)
    if fire_at_utc is None:
        return text_content(
            f"Reminder not set: could not parse 'at' = {at_raw!r}. "
            "Use ISO8601 format, e.g. '2026-05-04T17:00:00+05:30'."
        )

    try:
        cadence = _build_reminder_cadence(
            fire_at_utc=fire_at_utc, recurrence=recurrence, user_tz=user_tz
        )
    except Exception:
        logger.exception("remind: cadence build failed")
        return text_content("Reminder not set: could not build cadence.")

    try:
        from donna.attention.firing import schedule_reminder

        result = await schedule_reminder(
            user_id=user_id,
            message=text,
            cadence=cadence,
            origin=origin,
        )
    except Exception:
        logger.exception("remind: schedule_reminder failed")
        return text_content("Reminder not set: backend error.")

    schedule_id = result.get("schedule_id") if isinstance(result, dict) else None
    fire_str = fire_at_utc.strftime("%Y-%m-%d %H:%M UTC")
    rec_str = f", recurs {recurrence}" if recurrence else ""
    return text_content(
        f"reminder set for {fire_str}{rec_str} — schedule_id={schedule_id}"
    )


@tool(
    "list_reminders",
    (
        "List pending one-shot and recurring reminders for this user. "
        "Use before cancel_reminder to discover schedule_ids. "
        "Do NOT use for attention-linked schedules — those come from list_attentions. "
        "Do NOT call speculatively without a user ask."
    ),
    {"type": "object", "properties": {}},
)
@traceable(name="donna.tool.list_reminders", run_type="tool")
async def list_reminders(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("No reminders.")
    try:
        from donna.attention.firing import list_unattached_reminders
    except Exception:
        logger.exception("list_reminders: backend imports unavailable")
        return text_content("No reminders (backend unavailable).")
    try:
        rows = await list_unattached_reminders(user_id)
    except Exception:
        logger.exception("list_reminders: db read failed")
        return text_content("No reminders (db error).")
    if not rows:
        return text_content("No reminders.")
    lines: list[str] = []
    for r in rows[:20]:
        rec = r.get("recurrence") or "one-shot"
        msg = r.get("message") or "(no message)"
        lines.append(f"- {r['fire_at']}  ({rec})  {msg}  [schedule_id={r['schedule_id']}]")
    if len(rows) > 20:
        lines.append(f"(showing 20 of {len(rows)})")
    return text_content("\n".join(lines))


@tool(
    "cancel_reminder",
    (
        "Cancel a single reminder by schedule_id. Idempotent. Use when the "
        "user explicitly says to cancel / forget / drop a reminder. Get the "
        "schedule_id from list_reminders first if you do not have it. "
        "Do NOT use to cancel attention-linked schedules — those need "
        "cancel_attention. Do NOT cancel without an explicit user instruction."
    ),
    {
        "type": "object",
        "required": ["schedule_id"],
        "properties": {
            "schedule_id": {
                "type": "string",
                "description": "The id returned by remind / list_reminders.",
            },
        },
    },
)
@traceable(name="donna.tool.cancel_reminder", run_type="tool")
async def cancel_reminder(args):
    user_id = _current_user_id()
    schedule_id = str(args.get("schedule_id") or "").strip()
    if not user_id:
        return text_content("Cancel failed: no user_id in scope.")
    if not schedule_id:
        return text_content(
            "Cancel failed: 'schedule_id' is required. Call list_reminders to discover it first."
        )
    try:
        from donna.attention.firing import cancel_pending_fires_by_schedule_id
    except Exception:
        logger.exception("cancel_reminder: backend unavailable")
        return text_content("Cancel failed: backend unavailable.")
    try:
        deleted = await cancel_pending_fires_by_schedule_id(schedule_id, user_id=user_id)
    except Exception:
        logger.exception("cancel_reminder: db delete failed")
        return text_content("Cancel failed: db error.")
    if deleted == 0:
        return text_content(
            f"Cancel: nothing pending for schedule_id={schedule_id} "
            "(already fired, unknown, or attention-linked — try cancel_attention)."
        )
    return text_content(f"reminder cancelled (schedule_id={schedule_id}).")
