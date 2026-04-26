"""Calendar spawner — turn calendar events into attentions.

``maybe_spawn(event, user_id)`` is the only public entry point.
Wired into:

- ``backend.integrations.calendar_ingest.ingest_calendar_event``
  (post-upsert, try/except, non-blocking)
- ``backend.memory.jobs.spawner_worker`` (daily 24h-ahead sweep)

Classification is hybrid: regex/keyword first against the templates
in ``templates.json``; ambiguous events (long, has external attendees
in the title or attendee list, no obvious category) drop through to a
Haiku 4.5 fallback that picks ``stakes_meeting`` vs drop. Routine
recurring events are intentionally left to the existing
``CalendarRecurrenceProposer`` — we never spawn for those here.

The event passed in is either a raw Google Calendar dict OR a
``CalendarEntry`` row. The shape adapter normalises both.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from proactive.spawners.dedup import SpawnerDedupLedger
from proactive.spawners.materialise import materialise_intents
from proactive.spawners.shape import InferredIntent, SpawnConfidence
from proactive.spawners.templates import calendar_templates

logger = logging.getLogger(__name__)


# Window for "is this a real future event we should spawn for?"
# Anything more than 14 days out is probably noise; the daily sweep
# re-evaluates everything in the next 24h anyway.
_MAX_LOOKAHEAD_DAYS = 14
_MIN_LEAD_MINUTES = 5

# Used by the social/no-stakes drop heuristic.
_SOCIAL_KEYWORDS = frozenset(
    {
        "lunch", "coffee", "drinks", "dinner", "happy hour",
        "social", "birthday", "party",
    }
)

# Routine recurring titles — leave these to CalendarRecurrenceProposer.
_ROUTINE_KEYWORDS = frozenset(
    {
        "standup", "sync", "weekly", "1:1", "1-1", "one on one",
        "retro", "demo", "all hands", "all-hands", "office hours",
    }
)


@dataclass(frozen=True)
class _NormalizedEvent:
    event_id: str
    title: str
    start_utc: datetime
    end_utc: datetime | None
    duration_minutes: int
    attendee_emails: tuple[str, ...]


async def maybe_spawn(
    event: Any,
    user_id: str,
    *,
    ledger: SpawnerDedupLedger | None = None,
) -> list[str]:
    """Classify the event, spawn matching templates, return new attention ids.

    Returns ``[]`` for any of: skipped category, dedup hit, classifier
    drop, or a spawner failure. Never raises.
    """
    if not user_id:
        return []
    try:
        normalised = _normalise_event(event)
    except Exception:
        logger.exception("calendar_spawner: normalise failed")
        return []
    if normalised is None:
        return []

    if not _is_within_lookahead(normalised.start_utc):
        return []

    category = _classify_category(normalised)
    if category is None:
        try:
            category = await _classify_with_haiku(normalised)
        except Exception:
            logger.exception("calendar_spawner: haiku fallback raised")
            category = None
    if category is None:
        return []

    if category == "_routine":
        return []

    user_tz = await _load_user_tz(user_id)
    intents = _build_intents(normalised, category, user_tz=user_tz)
    if not intents:
        return []
    return await materialise_intents(intents, user_id=user_id, ledger=ledger)


# ── Normalisation ───────────────────────────────────────────────────────────


def _normalise_event(event: Any) -> _NormalizedEvent | None:
    """Coerce either a Google Calendar dict or a CalendarEntry row."""
    if event is None:
        return None
    if isinstance(event, dict):
        event_id = event.get("id") or event.get("google_event_id") or ""
        title = (event.get("summary") or event.get("title") or "").strip()
        start = _parse_dt(event.get("start"))
        end = _parse_dt(event.get("end"))
        attendees = tuple(
            str(a.get("email") or "").lower()
            for a in (event.get("attendees") or [])
            if isinstance(a, dict)
        )
    else:
        event_id = (
            getattr(event, "google_event_id", None) or getattr(event, "id", "")
        )
        title = (getattr(event, "title", "") or "").strip()
        start = _ensure_utc_dt(getattr(event, "start_time", None))
        end = _ensure_utc_dt(getattr(event, "end_time", None))
        attendees = ()

    if not event_id or not start:
        return None
    if not title:
        title = "(no title)"
    duration = 0
    if end:
        duration = max(0, int((end - start).total_seconds() / 60))
    return _NormalizedEvent(
        event_id=str(event_id),
        title=title,
        start_utc=start,
        end_utc=end,
        duration_minutes=duration,
        attendee_emails=attendees,
    )


def _parse_dt(spec: Any) -> datetime | None:
    if spec is None:
        return None
    if isinstance(spec, datetime):
        return _ensure_utc_dt(spec)
    if isinstance(spec, dict):
        raw = spec.get("dateTime") or spec.get("date")
    else:
        raw = spec
    if not raw:
        return None
    raw = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ensure_utc_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_within_lookahead(start_utc: datetime) -> bool:
    now = datetime.now(timezone.utc)
    delta = start_utc - now
    if delta < timedelta(minutes=_MIN_LEAD_MINUTES):
        return False
    if delta > timedelta(days=_MAX_LOOKAHEAD_DAYS):
        return False
    return True


# ── Classification ──────────────────────────────────────────────────────────


def _classify_category(event: _NormalizedEvent) -> str | None:
    """Regex/keyword pass. Returns category key or '_routine' or None."""
    title_low = event.title.lower()

    if _matches_any(title_low, _ROUTINE_KEYWORDS):
        return "_routine"

    if _matches_any(title_low, _SOCIAL_KEYWORDS):
        # Drop social events — LOW confidence per templates.
        return None

    cal = calendar_templates()
    for category, cfg in cal.items():
        keywords = cfg.get("category_keywords") or []
        if any(kw in title_low for kw in keywords):
            return category

    return None


def _matches_any(text: str, tokens: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(tok)}\b", text) for tok in tokens)


async def _classify_with_haiku(event: _NormalizedEvent) -> str | None:
    """Fallback for ambiguous events. Returns 'stakes_meeting' or None.

    Cheap rule: meeting ≥ 45 min with ≥ 2 attendees is stakes-shaped.
    Otherwise drop. The Haiku call is gated on
    ``DONNA_SPAWNER_HAIKU_FALLBACK=1`` so cost stays predictable; the
    deterministic rule below always runs.
    """
    if event.duration_minutes >= 45 and len(event.attendee_emails) >= 2:
        return "stakes_meeting"
    if os.environ.get("DONNA_SPAWNER_HAIKU_FALLBACK") != "1":
        return None
    # Real Haiku call would land here. Kept as a deterministic stub
    # so tests don't need network and dev cost is zero by default.
    return None


# ── Intent building ─────────────────────────────────────────────────────────


def _build_intents(
    event: _NormalizedEvent,
    category: str,
    *,
    user_tz: str,
) -> list[InferredIntent]:
    cal = calendar_templates()
    cfg = cal.get(category) or {}
    templates = cfg.get("templates") or []
    out: list[InferredIntent] = []
    zone = _resolve_zone(user_tz)

    for tpl in templates:
        try:
            intent = _intent_from_template(event, category, tpl, zone)
        except Exception:
            logger.exception(
                "calendar_spawner: intent build failed event=%s tpl=%s",
                event.event_id,
                tpl.get("id"),
            )
            continue
        if intent is None:
            continue
        out.append(intent)
    return out


def _intent_from_template(
    event: _NormalizedEvent,
    category: str,
    tpl: dict[str, Any],
    zone: ZoneInfo,
) -> InferredIntent | None:
    template_id = str(tpl.get("id") or "")
    if not template_id:
        return None
    confidence = SpawnConfidence.parse(tpl.get("confidence"))
    if confidence is SpawnConfidence.LOW:
        return None

    offset = int(tpl.get("offset_minutes_before") or 0)
    fire_utc = event.start_utc - timedelta(minutes=offset)
    if fire_utc <= datetime.now(timezone.utc) + timedelta(minutes=_MIN_LEAD_MINUTES):
        return None

    fire_local = fire_utc.astimezone(zone)
    when_phrase = _when_phrase(fire_local)
    time_phrase = _time_phrase(fire_local)
    text_template = str(tpl.get("intent") or "")
    text = text_template.format(
        title=event.title,
        time_local=time_phrase,
        when=when_phrase,
    )

    dedup_key = f"calendar:{event.event_id}:{template_id}"
    return InferredIntent(
        text=text,
        confidence=confidence,
        dedup_key=dedup_key,
        template_id=template_id,
        rationale=f"calendar event matched category={category}",
        signal={
            "event_id": event.event_id,
            "category": category,
            "fire_at_utc": fire_utc.isoformat(),
            "title": event.title,
        },
    )


def _resolve_zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo("UTC")


def _when_phrase(local_dt: datetime) -> str:
    today_local = datetime.now(local_dt.tzinfo).date()
    delta_days = (local_dt.date() - today_local).days
    if delta_days <= 0:
        return "today"
    if delta_days == 1:
        return "tomorrow"
    weekday = local_dt.strftime("%A").lower()
    if delta_days <= 6:
        return weekday
    return local_dt.strftime("%Y-%m-%d")


def _time_phrase(local_dt: datetime) -> str:
    hour = local_dt.hour
    minute = local_dt.minute
    suffix = "am" if hour < 12 else "pm"
    h12 = hour % 12 or 12
    if minute == 0:
        return f"{h12}{suffix}"
    return f"{h12}:{minute:02d}{suffix}"


async def _load_user_tz(user_id: str) -> str:
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import User
    except Exception:
        return "Asia/Singapore"
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
        if user and getattr(user, "timezone", None):
            return str(user.timezone)
    except Exception:
        logger.exception("calendar_spawner: tz lookup failed user=%s", user_id[:8])
    return "Asia/Singapore"


# ── Daily sweep entry point ─────────────────────────────────────────────────


async def sweep_upcoming(user_id: str, *, hours: int = 24) -> list[str]:
    """For the daily sweep: re-evaluate events firing in the next ``hours``.

    Idempotent — the dedup ledger drops anything we've already spawned.
    """
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import CalendarEntry
    except Exception:
        return []
    horizon_utc = datetime.now(timezone.utc) + timedelta(hours=hours)
    horizon_naive = horizon_utc.replace(tzinfo=None)
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(CalendarEntry)
                    .where(CalendarEntry.user_id == user_id)
                    .where(CalendarEntry.start_time <= horizon_naive)
                )
            ).scalars().all()
    except Exception:
        logger.exception("calendar_spawner: sweep query failed user=%s", user_id[:8])
        return []
    out: list[str] = []
    for row in rows:
        ids = await maybe_spawn(row, user_id)
        out.extend(ids)
    return out
