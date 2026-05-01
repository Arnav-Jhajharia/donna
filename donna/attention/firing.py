"""Attention firing tier — turns Cadence into concrete DonnaSchedule fires.

This module is the bridge between the in-memory ``Attention`` primitive and
the durable postgres queue the schedule worker drains. It owns three jobs:

1. ``compute_next_fire(cadence, after, tz)`` — pure function that resolves
   ONE_SHOT/SCHEDULED cadences to the next absolute UTC datetime.
2. ``materialize_next_fire(...)`` — inserts a single ``DonnaSchedule`` row
   wired back to the originating attention so the worker can both deliver
   the message and re-enqueue the next fire when the cadence is recurring.
3. ``cancel_pending_fires`` / ``snooze_pending_fires`` — admin operations
   the BRAIN tools call when the user says "cancel" or "snooze 10 minutes".

We deliberately materialize **one** future fire at a time per attention.
After the worker delivers it, it asks this module for the next one. This
keeps the queue small, makes cancellation a single DELETE, and avoids
double-firing if a worker resumes mid-batch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from donna.attention.schema import (
    Attention,
    AttentionSpec,
    Cadence,
)
from donna.attention.vocabulary import CadenceType, CardType, SourceType

logger = logging.getLogger(__name__)


# -- Cadence evaluation ------------------------------------------------------


def compute_next_fire(
    cadence: Cadence,
    *,
    after: datetime,
    tz: str = "UTC",
) -> datetime | None:
    """Return the next fire time strictly after ``after``, or None if exhausted.

    ``after`` may be naive (interpreted as UTC) or tz-aware. The returned
    datetime is always tz-aware UTC. Recurring cadences never return None
    here; only ONE_SHOT cadences whose trigger has passed do.
    """
    after_utc = _ensure_utc(after)
    params = cadence.params

    if cadence.type is CadenceType.ONE_SHOT:
        trigger = _parse_iso(params.get("trigger_at"))
        if trigger is None:
            return None
        return trigger if trigger > after_utc else None

    if cadence.type is CadenceType.SCHEDULED:
        if "interval_seconds" in params:
            interval = int(params["interval_seconds"])
            if interval <= 0:
                return None
            return after_utc + timedelta(seconds=interval)
        if "cron" in params:
            return _next_cron(params["cron"], after_utc, tz)
        if "monthly_day" in params:
            return _next_monthly_day(
                params["monthly_day"],
                int(params.get("hour", 9)),
                int(params.get("minute", 0)),
                after_utc,
                tz,
            )

    # ON_EVENT / ON_RELEVANCE / ON_DEMAND are not driven by this firing tier;
    # callers handle them separately (calendar sweep, condition watchers).
    return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    try:
        return _ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _next_cron(expr: str, after_utc: datetime, tz: str) -> datetime | None:
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")
    local_anchor = after_utc.astimezone(zone)
    try:
        itr = croniter(expr, local_anchor)
    except (ValueError, KeyError) as exc:
        logger.warning("invalid cron expression %r: %s", expr, exc)
        return None
    nxt_local = itr.get_next(datetime)
    if nxt_local.tzinfo is None:
        nxt_local = nxt_local.replace(tzinfo=zone)
    return nxt_local.astimezone(timezone.utc)


def _next_monthly_day(
    day: Any,
    hour: int,
    minute: int,
    after_utc: datetime,
    tz: str,
) -> datetime | None:
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")
    local = after_utc.astimezone(zone)
    candidate = _build_monthly_candidate(local.year, local.month, day, hour, minute, zone)
    if candidate is None or candidate <= local:
        year, month = local.year, local.month + 1
        if month > 12:
            year += 1
            month = 1
        candidate = _build_monthly_candidate(year, month, day, hour, minute, zone)
    if candidate is None:
        return None
    return candidate.astimezone(timezone.utc)


def _build_monthly_candidate(
    year: int, month: int, day: Any, hour: int, minute: int, zone: ZoneInfo
) -> datetime | None:
    if day == "last":
        target_day = _last_day_of_month(year, month)
    elif isinstance(day, int):
        target_day = min(day, _last_day_of_month(year, month))
    else:
        return None
    return datetime(year, month, target_day, hour, minute, tzinfo=zone)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last.day


# -- Recurrence metadata (denormalized for the worker) ----------------------


@dataclass(frozen=True)
class RecurrenceMeta:
    """Per-fire metadata persisted on DonnaSchedule.recurrence_meta.

    The worker reads this after a successful send to decide whether to
    materialize the next fire. We denormalize the cadence here so the
    worker never has to read the (potentially file-backed) attention store.
    """

    cadence_type: str
    cadence_params: dict[str, Any]
    user_tz: str
    question: str

    def as_jsonb(self) -> dict[str, Any]:
        return {
            "cadence_type": self.cadence_type,
            "cadence_params": dict(self.cadence_params),
            "user_tz": self.user_tz,
            "question": self.question,
        }

    @classmethod
    def from_jsonb(cls, raw: Any) -> "RecurrenceMeta | None":
        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                cadence_type=str(raw["cadence_type"]),
                cadence_params=dict(raw.get("cadence_params") or {}),
                user_tz=str(raw.get("user_tz") or "UTC"),
                question=str(raw.get("question") or ""),
            )
        except KeyError:
            return None

    @property
    def is_recurring(self) -> bool:
        return self.cadence_type == CadenceType.SCHEDULED.value

    def to_cadence(self) -> Cadence:
        return Cadence(
            type=CadenceType(self.cadence_type),
            params=dict(self.cadence_params),
        )


def recurrence_meta_for(spec: AttentionSpec, *, user_tz: str) -> RecurrenceMeta:
    """Extract the worker-relevant slice of an attention spec."""
    question = _ping_question(spec) or spec.title
    return RecurrenceMeta(
        cadence_type=spec.cadence.type.value,
        cadence_params=dict(spec.cadence.params),
        user_tz=user_tz,
        question=question,
    )


def _ping_question(spec: AttentionSpec) -> str:
    """For PING specs the USER_ELICITATION source carries the message text."""
    if spec.card is not CardType.PING:
        return ""
    for src in spec.sources:
        if src.type is SourceType.USER_ELICITATION:
            return str(src.params.get("question") or "")
    return ""


# -- Materialization (DonnaSchedule writes) ---------------------------------


async def materialize_next_fire(
    attention: Attention,
    *,
    user_id: str,
    user_phone: str,
    user_tz: str,
    after: datetime | None = None,
    origin: str | None = None,
) -> str | None:
    """Insert one DonnaSchedule row for the attention's next fire.

    ``user_id`` is the raw User.id FK (string) — passed in rather than read
    from ``attention.user_id`` because the attention model coerces handles
    to UUIDs and we need exact string equality with the users table.

    Returns the new schedule_id, or None if the cadence has no next fire
    (e.g. a ONE_SHOT whose trigger is already in the past). All errors
    surface to the caller — this is a write path; silent failures rot fast.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session

    base = after or datetime.now(timezone.utc)
    next_fire = compute_next_fire(attention.spec.cadence, after=base, tz=user_tz)
    if next_fire is None:
        return None

    fire_at_naive = next_fire.astimezone(timezone.utc).replace(tzinfo=None)
    meta = recurrence_meta_for(attention.spec, user_tz=user_tz)
    message_text = meta.question or attention.spec.title
    chosen_origin = origin or _origin_for(attention)

    async with async_session() as session:  # type: AsyncSession
        row = DonnaSchedule(
            user_id=user_id,
            phone=user_phone,
            fire_at=fire_at_naive,
            origin=chosen_origin,
            recurrence=_legacy_recurrence_label(attention.spec.cadence),
            context={
                "messages": [{"type": "text", "body": message_text}],
                "timezone": user_tz,
                "attention_id": str(attention.id),
            },
            attention_id=str(attention.id),
            recurrence_meta=meta.as_jsonb(),
            fired=False,
            status="pending",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


def _origin_for(attention: Attention) -> str:
    # Map AttentionOrigin.{USER_EXPLICIT, OFFER_ACCEPTED} → "user";
    # SHADOW_INFERRED → "donna" (proactively scheduled).
    return "user" if attention.origin.value != "shadow_inferred" else "donna"


def _legacy_recurrence_label(cadence: Cadence) -> str | None:
    """Best-effort fill-in for the legacy recurrence column.

    The worker reads ``recurrence_meta`` for re-enqueue decisions; this is
    purely so existing consumers (dashboards, logs) see something sensible.
    """
    if cadence.type is not CadenceType.SCHEDULED:
        return None
    if "interval_seconds" in cadence.params:
        return "interval"
    if "cron" in cadence.params:
        cron = str(cadence.params["cron"])
        if cron.endswith(" * * *"):
            return "daily"
        if cron.endswith(" 1-5"):
            return "weekdays"
        return "weekly"
    if "monthly_day" in cadence.params:
        return "monthly"
    return None


# -- Cancel / snooze ---------------------------------------------------------


async def cancel_pending_fires(attention_id: str) -> int:
    """Delete every unfired schedule row linked to an attention.

    Returns the number of rows removed. Used by the brain ``cancel_reminder``
    tool — the attention status update is a separate concern.
    """
    from sqlalchemy import delete

    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session

    async with async_session() as session:
        result = await session.execute(
            delete(DonnaSchedule)
            .where(DonnaSchedule.attention_id == attention_id)
            .where(DonnaSchedule.fired.is_(False))
        )
        await session.commit()
        return int(result.rowcount or 0)


async def snooze_pending_fires(
    attention_id: str, *, by_seconds: int
) -> datetime | None:
    """Push the next pending fire forward by ``by_seconds``.

    Returns the new fire_at (naive UTC) if a row was updated, else None.
    """
    from sqlalchemy import select, update

    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.attention_id == attention_id)
                .where(DonnaSchedule.fired.is_(False))
                .order_by(DonnaSchedule.fire_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        new_fire_at = row.fire_at + timedelta(seconds=int(by_seconds))
        await session.execute(
            update(DonnaSchedule)
            .where(DonnaSchedule.id == row.id)
            .values(fire_at=new_fire_at, status="pending", locked_at=None, locked_by=None)
        )
        await session.commit()
        return new_fire_at


async def list_pending_for_user(user_id: str) -> list[dict[str, Any]]:
    """Lightweight projection of unfired attention-linked rows for a user.

    Returns dicts the brain tool can render directly without exposing ORM
    objects across the boundary.
    """
    from sqlalchemy import select

    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session

    async with async_session() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.user_id == user_id)
                .where(DonnaSchedule.attention_id.is_not(None))
                .where(DonnaSchedule.fired.is_(False))
                .order_by(DonnaSchedule.fire_at.asc())
            )
        ).scalars().all()
    return [
        {
            "schedule_id": r.id,
            "attention_id": r.attention_id,
            "fire_at": r.fire_at.isoformat() if r.fire_at else None,
            "message": _peek_message(r.context),
            "recurrence_meta": r.recurrence_meta,
        }
        for r in rows
    ]


def _peek_message(context: Any) -> str:
    if not isinstance(context, dict):
        return ""
    messages = context.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            return str(first.get("body") or "")
    return ""


# -- Proactive brain fire ---------------------------------------------------


def build_fire_prompt(
    *,
    question: str,
    cadence_type: str,
    fire_at_iso: str,
    attention_id: str | None,
) -> str:
    """DEPRECATED: only used by the mirror-mode fallback path.

    The unified Tier 2 dispatcher constructs its own escalation prompt
    from the ``ProactiveEvent`` envelope in
    ``proactive.dispatcher._build_escalation_prompt``. This formatter is
    retained because ``fire_attention_via_brain`` still calls it under
    mirror mode (``DONNA_PROACTIVE_TIERED`` unset / 0) so behavior is
    bit-for-bit identical to pre-Phase-3.

    Phrased as a directive to Donna (matches the proactive-email pattern):
    here is what the user asked you to surface, here is when it was scheduled,
    decide if it is still relevant and send it in your voice. If you have
    signal that the user already did the thing or that the moment has passed,
    skip with a minimal terminator.
    """
    aid_line = f"attention_id: {attention_id}\n" if attention_id else ""
    return (
        "[proactive trigger: scheduled attention fires now]\n"
        "\n"
        f"the user previously asked you to ping them about: {question or '(no message)'}\n"
        f"cadence: {cadence_type}. scheduled fire: {fire_at_iso} UTC.\n"
        f"{aid_line}"
        "\n"
        "decide if the reminder is still relevant for the user RIGHT NOW. "
        "if yes, call send_burst with the reminder in your voice (do not "
        "echo the user's words verbatim). you can call recall / list_calendar / "
        "list_attentions before deciding.\n"
        "\n"
        "if you have signal that the user already did the thing, the moment "
        "has passed, or the reminder is stale, SKIP THIS FIRE: do not call "
        "send_burst at all. just end the turn. NEVER substitute a generic "
        "check-in like 'what's on your mind', 'hey', 'anything brewing', "
        "'how's it going' — those are noise, not reminders. silence is "
        "correct when the reminder no longer applies."
    )


async def fire_attention_via_brain(row: Any) -> list:
    """Run a proactive brain turn for an attention-linked schedule row.

    DEPRECATED for the gated path. With ``DONNA_PROACTIVE_TIERED=1`` the
    schedule worker routes attention fires through
    ``proactive.dispatcher.dispatch`` first; this function is invoked
    only for the mirror-mode fallback (and as a safety net when the
    dispatcher errors). Once mirror mode is retired, fold this into the
    dispatcher's escalation path and delete the standalone helper.

    Returns the outbound buffer (list of OutboundMessage / Delay) for the
    worker to send via WhatsAppChannel. Empty list means the brain chose
    to skip — the worker should still mark the row delivered.

    Errors propagate to the caller so the retry path on the worker can
    surface them in ``last_error``.
    """
    from donna_runtime.brain import donna_turn
    from donna_runtime.config import DonnaAgentConfig

    meta = row.recurrence_meta or {}
    question = str(meta.get("question") or "").strip()
    cadence_type = str(meta.get("cadence_type") or "one_shot")
    fire_at_iso = (
        row.fire_at.isoformat() if getattr(row, "fire_at", None) else "unknown"
    )

    prompt = build_fire_prompt(
        question=question,
        cadence_type=cadence_type,
        fire_at_iso=fire_at_iso,
        attention_id=row.attention_id,
    )

    cfg = DonnaAgentConfig(
        mode="proactive",
        user_id=row.user_id,
        user_phone=row.phone,
        # Workers run in their own Railway container with no filesystem
        # access to the API container's SDK session store. Resuming a
        # session_id saved by a reactive turn would crash the CLI subprocess
        # ("session not found") and ship the brain-failure fallback.
        # RECENT CHAT in render_turn_context already provides conversation
        # context for the proactive prompt.
        stateless_sessions=True,
    )
    state = {
        "user_id": row.user_id,
        "raw_input": prompt,
        "user_message": prompt,
        "phone": row.phone,
        "trigger": {
            "source": "attention_fire",
            "attention_id": row.attention_id,
            "schedule_id": row.id,
            "cadence_type": cadence_type,
            "fire_at": fire_at_iso,
        },
    }

    result = await donna_turn(state, cfg)
    outbound = result.get("_outbound") if isinstance(result, dict) else None
    return list(outbound) if outbound else []
