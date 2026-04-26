"""Observation spawner — turn an Observation row into attentions.

``maybe_spawn(observation, user_id)`` is the only public entry point.
Wired into ``donna_runtime.tools.log_observation`` post-commit
(try/except, never breaks the original tool).

Templates and confidences live in ``templates.json``. The four
shapes recognised today:

- drinking_event evening → HIGH LIVE one-shot ping at 09:00 next-day local
- sleep regression (2+ <6h nights in past 3) → HIGH LIVE one-shot ping
  at user's typical sleep_time tonight
- mood_low → MEDIUM SHADOW 24h check-in
- skipped meal → drop (no template)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from proactive.spawners.dedup import SpawnerDedupLedger
from proactive.spawners.materialise import materialise_intents
from proactive.spawners.shape import InferredIntent, SpawnConfidence
from proactive.spawners.templates import observation_templates

logger = logging.getLogger(__name__)


async def maybe_spawn(
    observation: Any,
    user_id: str,
    *,
    ledger: SpawnerDedupLedger | None = None,
) -> list[str]:
    """Classify the observation, spawn matching templates, return ids.

    Never raises. Returns ``[]`` for: dropped types, dedup hits, or
    spawner failures.
    """
    if not user_id or observation is None:
        return []
    obs = _normalise(observation)
    if obs is None:
        return []

    user_tz_name = await _load_user_tz(user_id)
    zone = _resolve_zone(user_tz_name)
    user_facts = await _load_user_facts(user_id)

    intents: list[InferredIntent] = []
    intents.extend(_drinking_intents(obs, zone))
    intents.extend(await _sleep_regression_intents(obs, user_id, zone, user_facts))
    intents.extend(_mood_low_intents(obs))
    if not intents:
        return []
    return await materialise_intents(intents, user_id=user_id, ledger=ledger)


# ── Normalisation ───────────────────────────────────────────────────────────


class _Obs:
    __slots__ = ("id", "type", "fields", "raw", "event_time_utc")

    def __init__(
        self,
        *,
        id: str,
        type: str,
        fields: dict[str, Any],
        raw: str,
        event_time_utc: datetime,
    ) -> None:
        self.id = id
        self.type = type
        self.fields = fields
        self.raw = raw
        self.event_time_utc = event_time_utc


def _normalise(observation: Any) -> _Obs | None:
    obs_id = getattr(observation, "id", None) or (
        observation.get("id") if isinstance(observation, dict) else None
    )
    obs_type = getattr(observation, "type", None) or (
        observation.get("type") if isinstance(observation, dict) else ""
    )
    fields = getattr(observation, "fields", None)
    if fields is None and isinstance(observation, dict):
        fields = observation.get("fields") or {}
    fields = fields or {}
    raw = getattr(observation, "raw", None) or (
        observation.get("raw") if isinstance(observation, dict) else ""
    )
    event_time = getattr(observation, "event_time", None) or (
        observation.get("event_time") if isinstance(observation, dict) else None
    )
    if not obs_id or not obs_type:
        return None
    if isinstance(event_time, str):
        try:
            event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            event_time = None
    if not isinstance(event_time, datetime):
        return None
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return _Obs(
        id=str(obs_id),
        type=str(obs_type).lower().strip(),
        fields=dict(fields),
        raw=str(raw or ""),
        event_time_utc=event_time.astimezone(timezone.utc),
    )


def _resolve_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


# ── Drinking ────────────────────────────────────────────────────────────────


def _drinking_intents(obs: _Obs, zone: ZoneInfo) -> list[InferredIntent]:
    if obs.type not in ("drinking_event", "drinking", "alcohol"):
        return []
    cfg = (observation_templates().get("drinking_event") or {})
    templates = cfg.get("templates") or []
    if not templates:
        return []
    local_event = obs.event_time_utc.astimezone(zone)
    out: list[InferredIntent] = []
    for tpl in templates:
        start = int(tpl.get("evening_window_start_hour", 18))
        end = int(tpl.get("evening_window_end_hour", 3))
        if not _is_evening(local_event.hour, start, end):
            continue
        target_local = _next_morning(
            local_event,
            hour=int(tpl.get("fire_local_hour", 9)),
            minute=int(tpl.get("fire_local_minute", 0)),
            next_day=bool(tpl.get("next_day", True)),
        )
        if target_local <= datetime.now(zone):
            continue
        text = str(tpl.get("intent") or "").strip()
        if not text:
            continue
        template_id = str(tpl.get("id") or "drinking_hydration")
        out.append(
            InferredIntent(
                text=text,
                confidence=SpawnConfidence.parse(tpl.get("confidence")),
                dedup_key=f"obs:{obs.id}:{template_id}",
                template_id=template_id,
                rationale="drinking event in the evening; hydrate next morning.",
                signal={
                    "obs_id": obs.id,
                    "fire_at_local": target_local.isoformat(),
                },
            )
        )
    return out


def _is_evening(local_hour: int, start: int, end: int) -> bool:
    """Window crosses midnight: 18..23 OR 0..2 means evening if start=18, end=3."""
    if start <= end:
        return start <= local_hour < end
    return local_hour >= start or local_hour < end


def _next_morning(
    local_event: datetime, *, hour: int, minute: int, next_day: bool
) -> datetime:
    base_date = local_event.date()
    if next_day:
        base_date = base_date + timedelta(days=1)
    return datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        hour,
        minute,
        tzinfo=local_event.tzinfo,
    )


# ── Sleep regression ────────────────────────────────────────────────────────


async def _sleep_regression_intents(
    obs: _Obs,
    user_id: str,
    zone: ZoneInfo,
    user_facts: dict[str, Any],
) -> list[InferredIntent]:
    cfg = (observation_templates().get("sleep_regression") or {})
    obs_types = set(cfg.get("obs_types") or ["sleep"])
    if obs.type not in obs_types:
        return []
    trigger = cfg.get("trigger") or {}
    min_short = int(trigger.get("min_short_nights", 2))
    lookback = int(trigger.get("lookback_nights", 3))
    max_hours = float(trigger.get("max_hours", 6.0))

    hours_now = _sleep_hours(obs)
    if hours_now is None or hours_now > max_hours:
        return []

    short_count = await _count_short_sleep_nights(
        user_id=user_id,
        cutoff_utc=obs.event_time_utc - timedelta(days=lookback),
        until_utc=obs.event_time_utc - timedelta(hours=1),
        max_hours=max_hours,
    )
    # +1 for the current obs, which already triggered max_hours check.
    if short_count + 1 < (min_short + 1):
        return []

    templates = cfg.get("templates") or []
    if not templates:
        return []
    sleep_time_str = str(user_facts.get("sleep_time") or "").strip()
    out: list[InferredIntent] = []
    today_local = datetime.now(zone)
    for tpl in templates:
        target_local = _resolve_tonight(
            today_local,
            sleep_time_str,
            fallback_hour=int(tpl.get("fallback_local_hour", 23)),
            fallback_minute=int(tpl.get("fallback_local_minute", 0)),
        )
        if target_local <= datetime.now(zone):
            continue
        text_template = str(tpl.get("intent") or "")
        time_phrase = _format_time(target_local)
        text = text_template.format(time_local=time_phrase)
        template_id = str(tpl.get("id") or "sleep_lights_out")
        out.append(
            InferredIntent(
                text=text,
                confidence=SpawnConfidence.parse(tpl.get("confidence")),
                dedup_key=f"obs:{obs.id}:{template_id}",
                template_id=template_id,
                rationale=(
                    f"{short_count + 1} short nights in the last "
                    f"{lookback} nights"
                ),
                signal={
                    "obs_id": obs.id,
                    "short_nights": short_count + 1,
                    "lookback_nights": lookback,
                    "fire_at_local": target_local.isoformat(),
                },
            )
        )
    return out


def _sleep_hours(obs: _Obs) -> float | None:
    val = obs.fields.get("hours") or obs.fields.get("sleep_hours")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def _count_short_sleep_nights(
    *,
    user_id: str,
    cutoff_utc: datetime,
    until_utc: datetime,
    max_hours: float,
) -> int:
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import Observation
    except Exception:
        return 0
    cutoff_naive = cutoff_utc.replace(tzinfo=None)
    until_naive = until_utc.replace(tzinfo=None)
    try:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .where(Observation.type == "sleep")
                    .where(Observation.event_time >= cutoff_naive)
                    .where(Observation.event_time <= until_naive)
                )
            ).scalars().all()
    except Exception:
        logger.exception(
            "obs_spawner: sleep count query failed user=%s", user_id[:8]
        )
        return 0
    count = 0
    for r in rows:
        f = getattr(r, "fields", None) or {}
        hv = f.get("hours") or f.get("sleep_hours")
        if hv is None:
            continue
        try:
            if float(hv) <= max_hours:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def _resolve_tonight(
    today_local: datetime,
    sleep_time_str: str,
    *,
    fallback_hour: int,
    fallback_minute: int,
) -> datetime:
    parsed = _parse_hhmm(sleep_time_str)
    if parsed is None:
        hour, minute = fallback_hour, fallback_minute
    else:
        hour, minute = parsed
    candidate = today_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= today_local:
        candidate = candidate + timedelta(days=1)
    return candidate


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def _format_time(local_dt: datetime) -> str:
    hour = local_dt.hour
    minute = local_dt.minute
    suffix = "am" if hour < 12 else "pm"
    h12 = hour % 12 or 12
    if minute == 0:
        return f"{h12}{suffix}"
    return f"{h12}:{minute:02d}{suffix}"


# ── Mood low ────────────────────────────────────────────────────────────────


def _mood_low_intents(obs: _Obs) -> list[InferredIntent]:
    cfg = (observation_templates().get("mood_low") or {})
    if obs.type != "mood":
        return []
    markers = [m.lower() for m in (cfg.get("markers") or [])]
    blob = " ".join(
        [obs.raw.lower(), " ".join(str(v).lower() for v in obs.fields.values())]
    )
    if not any(marker in blob for marker in markers):
        return []
    templates = cfg.get("templates") or []
    out: list[InferredIntent] = []
    for tpl in templates:
        text = str(tpl.get("intent") or "").strip()
        if not text:
            continue
        template_id = str(tpl.get("id") or "mood_low_checkin")
        out.append(
            InferredIntent(
                text=text,
                confidence=SpawnConfidence.parse(tpl.get("confidence")),
                dedup_key=f"obs:{obs.id}:{template_id}",
                template_id=template_id,
                rationale="mood-low marker in observation; soft check-in tomorrow.",
                signal={"obs_id": obs.id},
            )
        )
    return out


# ── User context loaders ────────────────────────────────────────────────────


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
        logger.exception("obs_spawner: tz lookup failed user=%s", user_id[:8])
    return "Asia/Singapore"


async def _load_user_facts(user_id: str) -> dict[str, Any]:
    """Pull sleep_time / wake_time directly off the User row."""
    try:
        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import User
    except Exception:
        return {}
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
        if user is None:
            return {}
        return {
            "sleep_time": getattr(user, "sleep_time", None),
            "wake_time": getattr(user, "wake_time", None),
        }
    except Exception:
        logger.exception("obs_spawner: facts lookup failed user=%s", user_id[:8])
        return {}
