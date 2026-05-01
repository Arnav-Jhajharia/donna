"""Source implementations.

Each Source reads input data for one attention and returns a
SourceResult (list of items + metadata). Sources are stateless;
they take an Attention and a DeriveContext and read what they need.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.memory.attention.pollers import ObservationDraft, get_poller
from backend.memory.attention.runtime import DeriveContext, SourceResult
from db.models import AttentionRow, Observation, OpenLoop
from db.session import async_session

logger = logging.getLogger(__name__)


class ObservationSource:
    """Read observations matching the attention's ``sources.params.tag``.

    Today we filter by:
      - user_id
      - observation type (heuristic: meal, expense, sleep, mood, exercise,
        habit, health, social, work_session — matched by tag prefix)
      - event_time within the user-local day window

    The deriver then runs whatever rollup logic the spec asks for.
    """

    # Map common source tags to observation types they should match.
    # Keep narrow — explicit is safer than greedy. Extend as needed.
    _TAG_TO_TYPES: dict[str, tuple[str, ...]] = {
        "meal_calories": ("meal",),
        "meal": ("meal",),
        "expense": ("expense",),
        "spend": ("expense",),
        "sleep_hours": ("sleep",),
        "sleep": ("sleep",),
        "mood": ("mood",),
        "exercise": ("exercise",),
        "habit": ("habit",),
        "water": ("habit", "health"),
        "hydration": ("habit", "health"),
    }

    async def read(
        self, *, attention: Any, ctx: DeriveContext
    ) -> SourceResult:
        try:
            spec = getattr(attention, "spec", None)
            sources = getattr(spec, "sources", []) if spec else []
            tag: str = ""
            for s in sources or []:
                params = getattr(s, "params", None)
                if params is None:
                    continue
                # params may be a Pydantic model or a plain dict.
                if isinstance(params, dict):
                    t = params.get("tag")
                else:
                    t = getattr(params, "tag", None)
                if t:
                    tag = str(t)
                    break
            if not tag:
                # No tag configured. Match by attention_id only.
                obs_types = ()
            else:
                obs_types = self._TAG_TO_TYPES.get(tag, ())
        except Exception:
            logger.exception("ObservationSource: spec read failed")
            return SourceResult()

        # Build the user-local day window in UTC for the query.
        day_start_local = ctx.user_local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end_local = day_start_local + timedelta(days=1)
        start_utc = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)

        try:
            async with async_session() as session:
                stmt = (
                    select(Observation)
                    .where(Observation.user_id == ctx.user_id)
                    .where(Observation.event_time >= start_utc)
                    .where(Observation.event_time < end_utc)
                )
                if obs_types:
                    stmt = stmt.where(Observation.type.in_(obs_types))
                # Also include any observation directly tagged to this attention,
                # in case a future hook wires attention_id at write time.
                stmt = stmt.order_by(Observation.event_time.asc()).limit(500)
                rows = (await session.execute(stmt)).scalars().all()
        except Exception:
            logger.exception(
                "ObservationSource: db read failed user=%s", ctx.user_id[:8]
            )
            return SourceResult()

        items: list[dict[str, Any]] = []
        for o in rows:
            items.append(
                {
                    "id": o.id,
                    "type": o.type,
                    "fields": dict(o.fields or {}),
                    "raw": o.raw or "",
                    "event_time": o.event_time.isoformat() if o.event_time else None,
                }
            )
        return SourceResult(
            items=items,
            meta={
                "tag": tag,
                "obs_types": list(obs_types),
                "day_start_utc": start_utc.isoformat(),
                "day_end_utc": end_utc.isoformat(),
                "n": len(items),
            },
        )


class TimeSource:
    """For ping / scheduled-only attentions: returns the next fire time.

    Most of the heavy lifting for time-based attentions is already done
    by the existing schedule_worker. This source exists so the runtime
    has a uniform shape — every attention has SOMETHING to read, even
    if it's just "the clock."
    """

    async def read(
        self, *, attention: Any, ctx: DeriveContext
    ) -> SourceResult:
        return SourceResult(
            items=[],
            meta={"clock": ctx.user_local_now.isoformat()},
        )


class PollerSource:
    """For ``card=event_stream`` attentions backed by external pollers.

    Walks ``spec.sources``, finds the first entry whose ``type`` matches a
    registered Poller, runs ``poller.fetch``, persists each draft via
    ``log_observation`` (so the schema enforcer + downstream tally hooks
    fire normally), then returns the drafts as items for the deriver.

    After a successful fetch, stamps the latest ``internal_date`` /
    ``event_time`` into ``AttentionRow.payload['poller_cursors'][type]``
    so the next tick picks up only new signal — pollers don't dedup
    themselves, the cursor does.

    No registered poller for the spec → returns an empty result. The
    engine falls back gracefully (downstream deriver returns count=0).
    """

    async def read(
        self, *, attention: Any, ctx: DeriveContext
    ) -> SourceResult:
        spec = getattr(attention, "spec", None)
        sources = getattr(spec, "sources", []) if spec else []
        source_type, source_params = _first_registered_poller_source(sources)
        if not source_type:
            return SourceResult(meta={"poller": None, "reason": "no_registered_source"})

        poller = get_poller(source_type)
        if poller is None:
            return SourceResult(
                meta={"poller": source_type, "reason": "not_registered"}
            )

        # Hydrate the AttentionRow payload onto the in-memory attention so
        # the poller can read its own cursor without an extra db call.
        await _hydrate_payload(attention)

        try:
            drafts: list[ObservationDraft] = await poller.fetch(
                attention=attention, ctx=ctx
            )
        except Exception:
            logger.exception(
                "PollerSource: poller %s raised user=%s",
                source_type,
                ctx.user_id[:8] if ctx.user_id else "",
            )
            return SourceResult(
                meta={"poller": source_type, "reason": "fetch_raised"}
            )

        if not drafts:
            return SourceResult(
                meta={"poller": source_type, "n": 0}
            )

        items: list[dict[str, Any]] = []
        latest_iso: str | None = None
        for d in drafts:
            obs_id = await _persist_draft(user_id=ctx.user_id, draft=d)
            event_iso = (
                d.fields.get("internal_date")
                or d.fields.get("event_time")
                or ctx.user_local_now.isoformat()
            )
            items.append(
                {
                    "id": obs_id,
                    "type": d.type,
                    "fields": dict(d.fields or {}),
                    "raw": d.raw,
                    "event_time": event_iso,
                }
            )
            if event_iso and (latest_iso is None or event_iso > latest_iso):
                latest_iso = event_iso

        if latest_iso:
            await _stamp_cursor(
                attention_id=str(getattr(attention, "id", "")),
                source_type=source_type,
                last_seen=latest_iso,
            )

        return SourceResult(
            items=items,
            meta={
                "poller": source_type,
                "params": source_params,
                "n": len(items),
                "last_seen": latest_iso,
            },
        )


def _first_registered_poller_source(
    sources: list[Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Return the first ``(type, params)`` pair whose type matches a registered
    poller. Skips the built-in ``internal_observations`` type."""
    if not sources:
        return "", {}
    for s in sources or []:
        s_type = getattr(s, "type", None)
        s_type_val = getattr(s_type, "value", s_type)
        if not s_type_val:
            continue
        if s_type_val in ("internal_observations",):
            continue
        if get_poller(s_type_val) is None:
            continue
        params = getattr(s, "params", None)
        if isinstance(params, dict):
            return s_type_val, dict(params)
        if params is None:
            return s_type_val, {}
        try:
            return s_type_val, dict(params.model_dump())  # type: ignore[attr-defined]
        except Exception:
            return s_type_val, {}
    return "", {}


async def _hydrate_payload(attention: Any) -> None:
    """Attach the latest AttentionRow.payload onto the in-memory attention.

    The poller reads ``attention._payload['poller_cursors']`` to know how
    far it polled last time. The pydantic Attention object doesn't carry
    that field, so we side-load it.
    """
    aid = str(getattr(attention, "id", "")) or ""
    if not aid:
        return
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(AttentionRow).where(AttentionRow.id == aid)
                )
            ).scalar_one_or_none()
            if row is not None:
                try:
                    object.__setattr__(attention, "_payload", dict(row.payload or {}))
                except Exception:
                    pass
    except Exception:
        logger.exception("PollerSource: payload hydrate failed id=%s", aid[:8])


async def _persist_draft(*, user_id: str, draft: ObservationDraft) -> str | None:
    """Write the draft as an observation. Best-effort; returns the obs id.

    Uses ``log_observation`` so all downstream hooks (schema enforcer,
    tally re-evaluation, situation brief refresh) fire normally. Tally
    re-eval is filtered to ``card_filter=("tally",)`` inside log_observation,
    so this won't recursively re-invoke event_stream evaluation.
    """
    try:
        from backend.memory.tools.log_observation import log_observation

        result = await log_observation(
            user_id=user_id,
            type=draft.type,
            fields=dict(draft.fields or {}),
            tags=dict(draft.tags or {}),
            raw=draft.raw or None,
            confidence=draft.confidence,
        )
        if isinstance(result, dict):
            data = result.get("data") or {}
            obs_id = data.get("id") if isinstance(data, dict) else None
            if obs_id:
                return str(obs_id)
        return None
    except Exception:
        logger.exception("PollerSource: log_observation failed user=%s", user_id[:8])
        return None


async def _stamp_cursor(
    *, attention_id: str, source_type: str, last_seen: str
) -> None:
    """Write the latest seen timestamp into AttentionRow.payload."""
    if not attention_id or not source_type or not last_seen:
        return
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(AttentionRow).where(AttentionRow.id == attention_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            payload = dict(row.payload or {})
            cursors = dict(payload.get("poller_cursors") or {})
            entry = dict(cursors.get(source_type) or {})
            entry["last_seen_internal_date"] = last_seen
            entry["last_polled_at"] = datetime.now(timezone.utc).isoformat()
            cursors[source_type] = entry
            payload["poller_cursors"] = cursors
            row.payload = payload
            flag_modified(row, "payload")
            await session.commit()
    except Exception:
        logger.exception(
            "PollerSource: cursor stamp failed id=%s type=%s",
            attention_id[:8] if attention_id else "",
            source_type,
        )


class OpenLoopSource:
    """Read open loops belonging to this attention or matching its subject."""

    async def read(
        self, *, attention: Any, ctx: DeriveContext
    ) -> SourceResult:
        try:
            async with async_session() as session:
                rows = (
                    await session.execute(
                        select(OpenLoop)
                        .where(OpenLoop.user_id == ctx.user_id)
                        .where(OpenLoop.status == "active")
                        .order_by(OpenLoop.created_at.desc())
                        .limit(50)
                    )
                ).scalars().all()
        except Exception:
            logger.exception(
                "OpenLoopSource: db read failed user=%s", ctx.user_id[:8]
            )
            return SourceResult()

        items = [
            {
                "id": r.id,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        return SourceResult(items=items, meta={"n": len(items)})
