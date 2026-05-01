"""Attention engine — picks (Source, Deriver, Surfacer) by card type.

The runtime entry point for "evaluate this attention now." Used by:
  - The observation hook (after a meal/expense/sleep observation lands)
  - The schedule_worker (when a cron fires)
  - The hourly backstop sweep (catches missed events + day rollovers)
  - Manual / test invocations

Writes ``current_state`` to ``AttentionRow.payload['current_state']`` and
records an ``AttentionTickRow`` audit entry per evaluation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.memory.attention.derivers import (
    AgeDeriver,
    CountDeriver,
    NextFireDeriver,
    SumDeriver,
)
from backend.memory.attention.runtime import (
    DeriveContext,
    Deriver,
    Source,
    SourceResult,
    SurfaceResult,
    Surfacer,
    run_attention_cycle,
)
from backend.memory.attention.sources import (
    ObservationSource,
    OpenLoopSource,
    PollerSource,
    TimeSource,
)
# Import registers concrete pollers as a side-effect; import order matters
# so the registry is populated before _pipeline_for runs.
from backend.memory.attention import poller_registry  # noqa: F401
from backend.memory.attention.surfacers import (
    PolicySurfacer,
    SilentSurfacer,
    StaleNudgeSurfacer,
)
from db.models import AttentionRow, AttentionTickRow, User
from db.session import async_session

logger = logging.getLogger(__name__)


def _pipeline_for(card: str) -> tuple[Source, Deriver, Surfacer] | None:
    """Pick the (Source, Deriver, Surfacer) tuple for a given card type."""
    card = (card or "").lower()
    if card == "tally":
        return ObservationSource(), SumDeriver(), PolicySurfacer()
    if card == "ping":
        return TimeSource(), NextFireDeriver(), SilentSurfacer()
    if card == "open_loop":
        return OpenLoopSource(), AgeDeriver(), StaleNudgeSurfacer()
    if card == "event_stream":
        # Pollers handle external streams (gmail, stocks, ...). The
        # PollerSource fans out via the registry; if the spec doesn't
        # name a registered poller, items come back empty and the
        # CountDeriver simply produces ``count=0``. Internal observations
        # for event_stream cards are still callable by authoring with
        # ``sources=[{type: "internal_observations", ...}]`` — handled
        # by the dedicated branch below.
        return PollerSource(), CountDeriver(), PolicySurfacer()
    if card == "brief":
        return ObservationSource(), CountDeriver(), SilentSurfacer()
    if card == "prep_doc":
        return TimeSource(), NextFireDeriver(), SilentSurfacer()
    return None


def _user_local_now(tz_name: str | None) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name or "Asia/Kolkata"))
    except Exception:
        return datetime.now(ZoneInfo("Asia/Kolkata"))


async def _load_attention(attention_id: str) -> Any | None:
    """Load the in-memory ``Attention`` (pydantic) for an attention id."""
    try:
        from donna.attention.store import AttentionStore

        store = AttentionStore()
        return store.get(attention_id)
    except Exception:
        logger.exception("engine: store.get failed id=%s", attention_id[:8])
        return None


async def evaluate_attention(
    *, attention_id: str, trigger: str = "manual"
) -> dict[str, Any] | None:
    """Run one full cycle for a single attention.

    Returns the new ``current_state`` (or None if evaluation failed).
    Side-effects:
      - Updates ``AttentionRow.payload['current_state']`` and ``last_update_at``
      - Inserts an ``AttentionTickRow`` audit record
      - If the surfacer returned a burst/escalation/nudge, returns the
        intent in the state under ``_surface`` so the caller can deliver.
        (Delivery itself is the caller's job — keeps this engine pure.)
    """
    attention = await _load_attention(attention_id)
    if attention is None:
        logger.warning("engine: attention not found id=%s", attention_id)
        return None

    spec = getattr(attention, "spec", None)
    card_type = getattr(getattr(spec, "card", None), "value", None) or ""
    user_id_raw = getattr(attention, "user_id", "")
    user_id = str(user_id_raw) if user_id_raw else ""
    if not card_type or not user_id:
        logger.warning("engine: missing card/user attention=%s", attention_id[:8])
        return None

    pipeline = _pipeline_for(card_type)
    if pipeline is None:
        logger.debug(
            "engine: no pipeline for card=%s id=%s", card_type, attention_id[:8]
        )
        return None
    source, deriver, surfacer = pipeline

    # Resolve user timezone
    tz_name = "Asia/Kolkata"
    try:
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user and user.timezone:
                tz_name = user.timezone
    except Exception:
        logger.exception("engine: user load failed user=%s", user_id[:8])

    user_local_now = _user_local_now(tz_name)
    user_local_day = user_local_now.date().isoformat()

    ctx = DeriveContext(
        user_id=user_id,
        user_local_now=user_local_now,
        user_local_day=user_local_day,
    )

    try:
        state, surface = await run_attention_cycle(
            attention=attention,
            source=source,
            deriver=deriver,
            surfacer=surfacer,
            ctx=ctx,
            trigger=trigger,
        )
    except Exception:
        logger.exception("engine: cycle raised id=%s", attention_id[:8])
        return None

    # Persist state + audit row.
    await _persist_state(
        attention_id=attention_id,
        state=state,
        surface=surface,
        trigger=trigger,
    )

    # Side-effect: if the surfacer wants to fire (escalation / nudge / burst),
    # hand it to the delivery layer. Delivery is best-effort and respects
    # the user's shadow/live mode setting.
    if surface.kind in {"escalation", "nudge", "burst"} and surface.message:
        try:
            from backend.memory.attention.delivery import deliver_surface

            await deliver_surface(
                user_id=user_id,
                attention_id=attention_id,
                surface=surface,
            )
        except Exception:
            logger.exception(
                "engine: delivery raised id=%s kind=%s",
                attention_id[:8],
                surface.kind,
            )

    out = dict(state)
    out["_surface"] = {"kind": surface.kind, "message": surface.message}
    return out


async def _persist_state(
    *,
    attention_id: str,
    state: dict[str, Any],
    surface: SurfaceResult,
    trigger: str,
) -> None:
    """Write current_state into AttentionRow.payload + insert tick audit row."""
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(AttentionRow).where(AttentionRow.id == attention_id)
                )
            ).scalar_one_or_none()
            if row is None:
                logger.warning(
                    "engine: AttentionRow missing id=%s — state not persisted",
                    attention_id[:8],
                )
                return
            payload = dict(row.payload or {})
            payload["current_state"] = state
            payload["last_update_at"] = datetime.now(timezone.utc).isoformat()
            row.payload = payload
            flag_modified(row, "payload")

            tick = AttentionTickRow(
                attention_id=attention_id,
                rendered_markdown=surface.message,
                source_counts={
                    "kind": surface.kind,
                    "trigger": trigger,
                    "value": state.get("value"),
                    "count": state.get("count"),
                },
            )
            session.add(tick)
            await session.commit()
    except Exception:
        logger.exception(
            "engine: persist failed id=%s trigger=%s", attention_id[:8], trigger
        )


async def evaluate_user_attentions(
    *, user_id: str, card_filter: tuple[str, ...] | None = None, trigger: str = "sweep"
) -> list[str]:
    """Evaluate all live attentions for a user. Returns ids that updated.

    ``card_filter`` lets callers narrow to e.g. only ``("tally",)`` after a
    meal observation lands. None = all live attentions.
    """
    updated: list[str] = []
    try:
        from donna.attention.schema import AttentionStatus
        from donna.attention.store import AttentionStore

        store = AttentionStore()
        rows = store.list(user_id=user_id, status=AttentionStatus.LIVE)
    except Exception:
        logger.exception("engine: list failed user=%s", user_id[:8])
        return updated

    for a in rows:
        spec = getattr(a, "spec", None)
        card = getattr(getattr(spec, "card", None), "value", None) or ""
        if card_filter and card not in card_filter:
            continue
        result = await evaluate_attention(
            attention_id=str(a.id), trigger=trigger
        )
        if result is not None:
            updated.append(str(a.id))
    return updated
