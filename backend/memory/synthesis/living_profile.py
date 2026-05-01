"""Nightly living profile synthesis (Donna v2).

Two callables:

- ``synthesize_full_profile(user_id)`` — full nightly pass. Reads chat
  messages, observations, open loops, calendar, user facts, and Graphiti
  facts. Produces every field of the v2 schema (situation, tensions,
  people, what-changed, watch-for, emotional read, rhythm, yesterday,
  today_shape).
- ``refresh_morning_digest(user_id)`` — cheaper morning pass that only
  regenerates ``yesterday`` and ``today_shape`` and merges them back
  into the existing profile JSONB.

Both write to ``users.living_profile``. The morning digest path is
designed to fire ~5 hours before the user's typical wake time so the
"how yesterday went / what today looks like" view is fresh by the
time they pick up their phone.

``synthesize_nightly_profile`` is kept as a back-compat alias for
``synthesize_full_profile`` — existing tests import that name.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from backend.memory.clients.graphiti import search_facts
from backend.memory.retrieval.structured import call_structured

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_FULL_PROMPT_PATH = _PROMPT_DIR / "living_profile.md"
_MORNING_PROMPT_PATH = _PROMPT_DIR / "living_profile_morning.md"

_MODEL = "claude-haiku-4-5-20251001"

_SEARCH_QUERIES = (
    "current situation challenges problems stress",
    "people relationships team colleagues",
    "goals progress milestones deadlines",
    "recent changes decisions updates",
)

_CHAT_LOOKBACK_DAYS = 14
_CHAT_MAX_MESSAGES = 80
_CHAT_MAX_CHARS_PER_MSG = 220

_OBSERVATION_LOOKBACK_DAYS = 30
_OBSERVATION_MAX = 60

_OPEN_LOOP_MAX = 10
_CALENDAR_LOOKBACK_DAYS = 7
_CALENDAR_LOOKAHEAD_DAYS = 7
_CALENDAR_MAX = 14
_GRAPH_FACT_MAX = 30

_MIN_SIGNAL_FOR_FULL_RUN = 5  # chat msgs OR observations OR graph facts combined


# --- Pydantic output schemas -------------------------------------------------


class _KeyPerson(BaseModel):
    name: str
    role: str = ""
    current_dynamic: str = ""


class _Rhythm(BaseModel):
    typical_wake_window: str = ""
    typical_first_engage_window: str = ""
    typical_message_gap_median_hours: float | None = None
    typical_quiet_hours: str = ""


class _YesterdayDigest(BaseModel):
    one_line: str = ""
    misses: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)


class _FullProfile(BaseModel):
    # Narrative is what Donna reads at turn time — a single alive paragraph
    # that captures who the user is right now. Other fields are sidecars
    # for downstream pattern miners and proactive triggers; they are NOT
    # rendered into the system prompt as bullet lists anymore.
    narrative: str = ""
    # Running themes spanning the full 14-30 day input window. Renders
    # as one short comma-joined line under the narrative so Donna has
    # ambient awareness of the longer arc, not just yesterday.
    running_themes: list[str] = Field(default_factory=list)
    current_situation: str = ""
    active_tensions: list[str] = Field(default_factory=list)
    key_people: list[_KeyPerson] = Field(default_factory=list)
    what_changed_this_week: list[str] = Field(default_factory=list)
    watch_for_tomorrow: list[str] = Field(default_factory=list)
    emotional_temperature: str = "focused"
    rhythm: _Rhythm = Field(default_factory=_Rhythm)
    yesterday: _YesterdayDigest = Field(default_factory=_YesterdayDigest)
    today_shape: str = ""


class _MorningDigest(BaseModel):
    # Same narrative principle for the morning refresh: one alive paragraph
    # is what Donna sees; structured fields back it up.
    narrative: str = ""
    yesterday: _YesterdayDigest = Field(default_factory=_YesterdayDigest)
    today_shape: str = ""


# --- Input assembly ----------------------------------------------------------


@dataclass(frozen=True)
class _UserContext:
    user_id: str
    name: str
    timezone_name: str
    facts: dict[str, Any] = field(default_factory=dict)
    chat_lines: tuple[str, ...] = field(default_factory=tuple)
    observation_lines: tuple[str, ...] = field(default_factory=tuple)
    open_loop_lines: tuple[str, ...] = field(default_factory=tuple)
    calendar_lines: tuple[str, ...] = field(default_factory=tuple)
    graph_fact_lines: tuple[str, ...] = field(default_factory=tuple)

    def total_signal(self) -> int:
        return (
            len(self.chat_lines)
            + len(self.observation_lines)
            + len(self.graph_fact_lines)
            + len(self.open_loop_lines)
        )


async def _load_user_basic(user_id: str) -> tuple[str, str, dict[str, Any]] | None:
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return None
        name = user.name if user.name else "the user"
        tz_name = user.timezone or "UTC"
        facts = dict(user.facts or {})
    return name, tz_name, facts


def _to_local_str(value: datetime | None, tz_name: str) -> str:
    """Render a UTC-naive datetime as user-local ``YYYY-MM-DD HH:MM``.

    Postgres stores ``ChatMessage.created_at`` and ``Observation.event_time``
    as UTC-naive. The synth's rhythm inference depends on seeing user-local
    wall-clock time — passing raw UTC strings made it call 23:30 UTC the
    "first engage window" for a Singapore user whose local time was 07:30.
    """
    if value is None:
        return "?"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    aware_utc = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")


async def _load_recent_chat_lines(
    user_id: str,
    *,
    lookback_days: int,
    max_messages: int,
    timezone_name: str,
) -> tuple[str, ...]:
    from sqlalchemy import select

    from backend.db.models import ChatMessage
    from backend.db.session import async_session

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=lookback_days
    )
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.user_id == user_id)
                    .where(ChatMessage.is_shadow.is_(False))
                    .where(ChatMessage.created_at >= since)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(max_messages)
                )
            ).scalars().all()
    except Exception:
        logger.exception("living_profile: chat fetch failed user=%s", user_id[:8])
        return ()

    lines: list[str] = []
    for row in reversed(rows):  # chronological
        if not row.content:
            continue
        ts = _to_local_str(row.created_at, timezone_name)
        body = row.content.strip().replace("\n", " ")
        if len(body) > _CHAT_MAX_CHARS_PER_MSG:
            body = body[: _CHAT_MAX_CHARS_PER_MSG - 3] + "..."
        marker = "P" if getattr(row, "is_proactive", False) else " "
        lines.append(f"[{ts}] {marker}{row.role}: {body}")
    return tuple(lines)


async def _load_recent_observation_lines(
    user_id: str,
    *,
    lookback_days: int,
    max_rows: int,
    timezone_name: str,
) -> tuple[str, ...]:
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.db.session import async_session

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=lookback_days
    )
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .where(Observation.event_time >= since)
                    .order_by(Observation.event_time.desc())
                    .limit(max_rows)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "living_profile: observation fetch failed user=%s", user_id[:8]
        )
        return ()

    lines: list[str] = []
    for row in reversed(rows):
        ts = _to_local_str(row.event_time, timezone_name)
        fields_compact = _compact_fields(row.fields or {})
        lines.append(f"[{ts}] {row.type}: {fields_compact}")
    return tuple(lines)


async def _load_open_loop_lines(user_id: str, *, max_rows: int) -> tuple[str, ...]:
    from sqlalchemy import select

    from backend.db.models import OpenLoop
    from backend.db.session import async_session

    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(OpenLoop)
                    .where(OpenLoop.user_id == user_id)
                    .order_by(OpenLoop.created_at.desc())
                    .limit(max_rows)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "living_profile: open loop fetch failed user=%s", user_id[:8]
        )
        return ()

    lines: list[str] = []
    for row in rows:
        status = getattr(row, "status", "?") or "?"
        content = (getattr(row, "content", None) or "").strip()
        if not content:
            continue
        created = (
            row.created_at.strftime("%Y-%m-%d") if row.created_at else "?"
        )
        lines.append(f"[{created}] [{status}] {content[:160]}")
    return tuple(lines)


async def _load_calendar_lines(
    user_id: str,
    *,
    lookback_days: int,
    lookahead_days: int,
    max_rows: int,
    timezone_name: str,
) -> tuple[str, ...]:
    from sqlalchemy import select

    from backend.db.models import CalendarEntry
    from backend.db.session import async_session

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=lookback_days)
    until = now + timedelta(days=lookahead_days)
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(CalendarEntry)
                    .where(CalendarEntry.user_id == user_id)
                    .where(CalendarEntry.start_time >= since)
                    .where(CalendarEntry.start_time <= until)
                    .order_by(CalendarEntry.start_time.asc())
                    .limit(max_rows)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "living_profile: calendar fetch failed user=%s", user_id[:8]
        )
        return ()

    lines: list[str] = []
    for row in rows:
        when = _to_local_str(row.start_time, timezone_name)
        title = (getattr(row, "title", None) or "untitled").strip()
        loc = (getattr(row, "location", None) or "").strip()
        suffix = f" @ {loc}" if loc else ""
        lines.append(f"[{when}] {title}{suffix}")
    return tuple(lines)


async def _load_graph_fact_lines(user_id: str, *, max_facts: int) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for q in _SEARCH_QUERIES:
        try:
            facts = await search_facts(user_id, q, limit=8)
        except Exception:
            logger.exception(
                "living_profile: graph fact search failed user=%s q=%r",
                user_id[:8], q,
            )
            continue
        for fact_row in facts:
            text = (fact_row.get("fact") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            valid = str(fact_row.get("valid_at") or "recent")[:10]
            out.append(f"[{valid}] {text}")
            if len(out) >= max_facts:
                break
        if len(out) >= max_facts:
            break
    return tuple(out)


def _compact_fields(value: dict[str, Any]) -> str:
    if not value:
        return "{}"
    parts: list[str] = []
    for key, item in list(value.items())[:5]:
        parts.append(f"{key}={item}")
    return ", ".join(parts)


def _format_facts(facts: dict[str, Any]) -> str:
    """Compact one-line-per-fact rendering of User.facts."""
    if not facts:
        return ""
    lines: list[str] = []
    for key, payload in facts.items():
        if isinstance(payload, dict):
            value = payload.get("value")
        else:
            value = payload
        if value is None or value == "":
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


async def _build_context(user_id: str) -> _UserContext | None:
    basic = await _load_user_basic(user_id)
    if basic is None:
        return None
    name, tz_name, facts = basic

    chat = await _load_recent_chat_lines(
        user_id,
        lookback_days=_CHAT_LOOKBACK_DAYS,
        max_messages=_CHAT_MAX_MESSAGES,
        timezone_name=tz_name,
    )
    observations = await _load_recent_observation_lines(
        user_id,
        lookback_days=_OBSERVATION_LOOKBACK_DAYS,
        max_rows=_OBSERVATION_MAX,
        timezone_name=tz_name,
    )
    open_loops = await _load_open_loop_lines(user_id, max_rows=_OPEN_LOOP_MAX)
    calendar = await _load_calendar_lines(
        user_id,
        lookback_days=_CALENDAR_LOOKBACK_DAYS,
        lookahead_days=_CALENDAR_LOOKAHEAD_DAYS,
        max_rows=_CALENDAR_MAX,
        timezone_name=tz_name,
    )
    graph_facts = await _load_graph_fact_lines(user_id, max_facts=_GRAPH_FACT_MAX)

    return _UserContext(
        user_id=user_id,
        name=name,
        timezone_name=tz_name,
        facts=facts,
        chat_lines=chat,
        observation_lines=observations,
        open_loop_lines=open_loops,
        calendar_lines=calendar,
        graph_fact_lines=graph_facts,
    )


# --- Prompt assembly ---------------------------------------------------------


def _load_prompt(path: Path, *, fallback: str) -> str:
    try:
        return path.read_text()
    except Exception:
        return fallback


def _build_full_prompt(ctx: _UserContext, *, now_local: str) -> str:
    template = _load_prompt(
        _FULL_PROMPT_PATH,
        fallback="Synthesize a full nightly profile and return structured JSON.",
    )
    return template.format(
        name=ctx.name,
        timezone=ctx.timezone_name,
        now_local=now_local,
        facts=_format_facts(ctx.facts) or "(none)",
        chat="\n".join(ctx.chat_lines) or "(no recent chat)",
        observations="\n".join(ctx.observation_lines) or "(no recent observations)",
        open_loops="\n".join(ctx.open_loop_lines) or "(no open loops)",
        calendar="\n".join(ctx.calendar_lines) or "(no calendar entries)",
        graph_facts="\n".join(ctx.graph_fact_lines) or "(no graph facts)",
    )


def _build_morning_prompt(
    ctx: _UserContext, *, existing: dict, now_local: str
) -> str:
    template = _load_prompt(
        _MORNING_PROMPT_PATH,
        fallback=(
            "Refresh the yesterday recap and today_shape from the latest chat,"
            " observations, and calendar. Return only those two fields as JSON."
        ),
    )
    existing_summary = json.dumps(
        {
            "current_situation": existing.get("current_situation", ""),
            "watch_for_tomorrow": existing.get("watch_for_tomorrow", []),
            "rhythm": existing.get("rhythm", {}),
            "key_people": existing.get("key_people", []),
        },
        indent=2,
    )
    return template.format(
        name=ctx.name,
        timezone=ctx.timezone_name,
        now_local=now_local,
        existing=existing_summary,
        chat="\n".join(ctx.chat_lines) or "(no recent chat)",
        observations="\n".join(ctx.observation_lines) or "(no recent observations)",
        calendar="\n".join(ctx.calendar_lines) or "(no calendar entries)",
    )


def _now_local_iso(timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).isoformat(timespec="minutes")


# --- Persistence -------------------------------------------------------------


async def _persist_profile(user_id: str, payload: dict) -> None:
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return
        user.living_profile = payload
        await session.commit()


async def _merge_morning_digest(user_id: str, digest: dict) -> dict | None:
    """Merge ``yesterday`` and ``today_shape`` into the existing profile.

    Leaves all other keys untouched. Returns the merged dict or None when
    the user row is missing.
    """
    from sqlalchemy import select

    from backend.db.models import User
    from backend.db.session import async_session

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return None
        existing = dict(user.living_profile) if user.living_profile else {}
        existing["yesterday"] = digest.get("yesterday") or {}
        existing["today_shape"] = digest.get("today_shape") or ""
        existing["yesterday_refreshed_at"] = datetime.now(timezone.utc).isoformat()
        user.living_profile = existing
        await session.commit()
        return existing


# --- Public API --------------------------------------------------------------


async def synthesize_full_profile(user_id: str) -> dict | None:
    """Run a full nightly synthesis for ``user_id`` and persist the result.

    Returns the profile dict on success, ``None`` when the user is missing,
    inputs are too thin, or the LLM call fails. Failure is logged, not
    raised — the worker reschedules.
    """
    ctx = await _build_context(user_id)
    if ctx is None:
        logger.info("living_profile: user=%s missing, skip", user_id[:8])
        return None

    if ctx.total_signal() < _MIN_SIGNAL_FOR_FULL_RUN:
        logger.info(
            "living_profile: user=%s thin signal (%d), skip",
            user_id[:8],
            ctx.total_signal(),
        )
        return None

    now_local = _now_local_iso(ctx.timezone_name)
    prompt = _build_full_prompt(ctx, now_local=now_local)
    profile = await call_structured(
        model=_MODEL,
        system_prompt=prompt,
        user_message="Synthesize.",
        schema=_FullProfile,
        max_tokens=1400,
        timeout=45.0,
    )
    if profile is None:
        logger.warning("living_profile: full synthesis returned None user=%s", user_id[:8])
        return None

    payload = profile.model_dump()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["yesterday_refreshed_at"] = payload["generated_at"]
    payload["signal"] = {
        "chat_msgs": len(ctx.chat_lines),
        "observations": len(ctx.observation_lines),
        "open_loops": len(ctx.open_loop_lines),
        "calendar": len(ctx.calendar_lines),
        "graph_facts": len(ctx.graph_fact_lines),
    }
    await _persist_profile(user_id, payload)
    logger.info(
        "living_profile: stored full user=%s signal=%s temp=%s",
        user_id[:8],
        payload["signal"],
        payload.get("emotional_temperature", "?"),
    )
    return payload


async def refresh_morning_digest(user_id: str) -> dict | None:
    """Regenerate ``yesterday`` and ``today_shape`` for ``user_id``.

    Reads the existing profile (if any), runs a cheaper Haiku pass, and
    merges the two fields back without disturbing the rest of the profile.
    Returns the merged dict, or ``None`` on failure or thin signal.
    """
    ctx = await _build_context(user_id)
    if ctx is None:
        return None

    if not ctx.chat_lines and not ctx.observation_lines and not ctx.calendar_lines:
        logger.info(
            "living_profile: morning digest user=%s no signal, skip",
            user_id[:8],
        )
        return None

    from backend.memory.user_facts.api import get_living_profile

    existing = await get_living_profile(user_id) or {}

    now_local = _now_local_iso(ctx.timezone_name)
    prompt = _build_morning_prompt(ctx, existing=existing, now_local=now_local)
    digest = await call_structured(
        model=_MODEL,
        system_prompt=prompt,
        user_message="Refresh.",
        schema=_MorningDigest,
        max_tokens=600,
        timeout=25.0,
    )
    if digest is None:
        logger.warning(
            "living_profile: morning digest returned None user=%s",
            user_id[:8],
        )
        return None

    merged = await _merge_morning_digest(user_id, digest.model_dump())
    if merged is not None:
        logger.info(
            "living_profile: morning digest merged user=%s",
            user_id[:8],
        )
    return merged


# Back-compat alias — existing callers and tests use this name.
synthesize_nightly_profile = synthesize_full_profile
