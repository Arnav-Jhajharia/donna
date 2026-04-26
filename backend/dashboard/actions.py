"""Dashboard action handlers.

The dashboard mutates server-side state through ``ActionVerb`` taps. This
module owns the per-verb logic so the HTTP layer stays thin. Today we
handle two verbs:

- ``accept_offered_attention`` flips an OFFERED Attention to LIVE,
  materializes a ``DonnaInstance(primitive=track)`` for TALLY and
  EVENT_STREAM cards, and triggers a dashboard recompose so the
  tracker-starter card is replaced by a tracker-grid on the next poll.
- ``dismiss_offered_attention`` flips an OFFERED Attention to REJECTED.

Both are idempotent: re-calling on a non-OFFERED attention is a no-op
that returns ``ok=False`` with a reason.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from db.models import DonnaInstance
from db.session import async_session
from donna.attention.noise import normalize_tracker_label

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcceptResult:
    ok: bool
    attention_id: str
    status: str | None = None
    instance_id: str | None = None
    instance_created: bool = False
    # Recompose runs in a background task so the accept response returns
    # in <1s instead of blocking on a 60s LLM call. Values:
    #   "scheduled" — the recompose task was spawned successfully
    #   "skipped"   — recompose was not needed (e.g. card type doesn't
    #                 affect the dashboard, or instance materialise
    #                 already returned False because nothing to do)
    #   "failed"    — couldn't even spawn the task (rare, logged)
    recomposed: str = "skipped"
    error: str | None = None


# Strong-reference set so fire-and-forget recompose tasks aren't garbage
# collected mid-flight. Python's asyncio docs warn that ``create_task``
# does NOT keep a strong reference; without this they can vanish on the
# next GC cycle. ``add_done_callback(discard)`` cleans up after the
# task finishes so the set doesn't grow unbounded.
_pending_recomposes: set[asyncio.Task[bool]] = set()


def _spawn_recompose(*, user_id: str) -> str:
    """Schedule a dashboard recompose to run after the request returns.

    Returns ``"scheduled"`` on success, ``"failed"`` if we couldn't
    even create the task.
    """
    try:
        task = asyncio.create_task(
            _recompose_after_accept(user_id=user_id),
            name=f"dashboard_recompose:{user_id[:8]}",
        )
    except Exception:
        logger.exception(
            "_spawn_recompose: failed to create task user=%s",
            user_id[:8] if user_id else "?",
        )
        return "failed"
    _pending_recomposes.add(task)
    task.add_done_callback(_pending_recomposes.discard)
    return "scheduled"


# Cards we materialize as a DonnaInstance(primitive=track). The other
# four card types (BRIEF, PREP_DOC, OPEN_LOOP, PING) live entirely
# inside the attention subsystem — accepting them only flips status.
_TRACKER_CARD_VALUES = frozenset({"tally", "event_stream"})


async def accept_offered_attention(
    *, user_id: str, attention_id: str
) -> AcceptResult:
    """Accept an OFFERED attention and run the LIVE-side work.

    Best-effort: if any post-flip step fails, we still report the
    flip as successful so the dashboard reflects the new state. The
    failure is logged for follow-up.
    """
    attention = _load_attention(attention_id)
    if attention is None:
        return AcceptResult(
            ok=False,
            attention_id=attention_id,
            error="attention not found",
        )
    if str(getattr(attention, "user_id", "")) != str(user_id):
        return AcceptResult(
            ok=False,
            attention_id=attention_id,
            error="attention belongs to another user",
        )

    try:
        from donna.attention.promote import accept_offer
    except Exception:
        logger.exception("accept_offered_attention: import failed")
        return AcceptResult(
            ok=False, attention_id=attention_id, error="backend unavailable"
        )

    updated = accept_offer(attention_id)
    if updated is None:
        # Already LIVE / RESOLVED / REJECTED — nothing to do.
        return AcceptResult(
            ok=False,
            attention_id=attention_id,
            status=getattr(attention.status, "value", None),
            error="attention is not OFFERED",
        )

    instance_id, created = await _maybe_materialize_instance(
        user_id=user_id, attention=updated
    )
    recomposed = _spawn_recompose(user_id=user_id)

    return AcceptResult(
        ok=True,
        attention_id=attention_id,
        status=getattr(updated.status, "value", None),
        instance_id=instance_id,
        instance_created=created,
        recomposed=recomposed,
    )


async def mark_reminder_done(
    *, user_id: str, reminder_id: str
) -> tuple[bool, str | None]:
    """Mark a ``DonnaSchedule`` row as fired/done.

    Tap-to-complete from the dashboard reminders block. Returns
    ``(ok, error)``. Idempotent: marking an already-done reminder is a
    no-op success. After a successful flip we kick off a recompose so
    the card disappears on the next dashboard poll.
    """
    from datetime import datetime, timezone

    from db.models import DonnaSchedule

    if not reminder_id:
        return False, "reminder_id is required"

    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(DonnaSchedule).where(DonnaSchedule.id == reminder_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return False, "reminder not found"
            if str(row.user_id) != str(user_id):
                return False, "reminder belongs to another user"
            if row.fired and row.status == "done":
                # Idempotent: already done. Don't re-fire the recompose
                # either — nothing changed for the dashboard.
                return True, None
            row.fired = True
            row.fired_at = datetime.now(timezone.utc).replace(tzinfo=None)
            row.status = "done"
            await session.commit()
    except Exception:
        logger.exception(
            "mark_reminder_done: db update failed user=%s reminder=%s",
            user_id[:8] if user_id else "?",
            reminder_id,
        )
        return False, "db error"

    _spawn_recompose(user_id=user_id)
    return True, None


async def dismiss_offered_attention(
    *, user_id: str, attention_id: str
) -> bool:
    attention = _load_attention(attention_id)
    if attention is None:
        return False
    if str(getattr(attention, "user_id", "")) != str(user_id):
        return False
    try:
        from donna.attention.promote import reject_offer
    except Exception:
        logger.exception("dismiss_offered_attention: import failed")
        return False
    return reject_offer(attention_id) is not None


def _load_attention(attention_id: str) -> Any | None:
    try:
        from donna.attention.store import AttentionStore
    except Exception:
        logger.exception("dashboard.actions: AttentionStore import failed")
        return None
    try:
        return AttentionStore().get(attention_id)
    except Exception:
        logger.exception("dashboard.actions: store.get failed id=%s", attention_id)
        return None


async def _maybe_materialize_instance(
    *, user_id: str, attention: Any
) -> tuple[str | None, bool]:
    """Create a ``DonnaInstance(primitive=track)`` for tracker cards.

    Returns ``(instance_id, created)``. ``created=False`` means an
    existing instance for the same (user, primitive, normalized_label)
    was reused. Normalization collapses common variants
    (``expense``/``expenses``/``daily expenses``) onto one row so we
    don't accumulate near-duplicates as the user iterates.
    """
    spec = getattr(attention, "spec", None)
    card = getattr(spec, "card", None)
    card_value = getattr(card, "value", "") or str(card or "").lower()
    if card_value not in _TRACKER_CARD_VALUES:
        return None, False

    subject = getattr(getattr(spec, "subject", None), "name", None)
    label = (subject or getattr(spec, "title", "") or "tracker").strip()
    if not label:
        return None, False

    normalized = normalize_tracker_label(label)
    config: dict[str, Any] = {
        "type": label,
        "normalized_label": normalized,
        "card_type": card_value,
        "from_attention_id": str(getattr(attention, "id", "")),
    }
    target = _extract_target(spec)
    if target is not None:
        config["target_per_day"] = target

    try:
        async with async_session() as session:
            # Pull active track-instances for this user, normalize each
            # label, and reuse if any matches. Sub-second on realistic
            # row counts (≤ 30 active instances per user); avoids the
            # need for a generated column or migration today.
            existing_rows = (
                (
                    await session.execute(
                        select(DonnaInstance)
                        .where(DonnaInstance.user_id == user_id)
                        .where(DonnaInstance.primitive == "track")
                        .where(DonnaInstance.status == "active")
                    )
                )
                .scalars()
                .all()
            )
            for row in existing_rows:
                if normalize_tracker_label(row.label) == normalized:
                    return row.id, False

            instance = DonnaInstance(
                user_id=user_id,
                primitive="track",
                connector="whatsapp_manual",
                label=label,
                config=config,
                status="active",
            )
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance.id, True
    except Exception:
        logger.exception(
            "accept_offered_attention: DonnaInstance materialize failed user=%s label=%s",
            user_id[:8] if user_id else "?",
            label,
        )
        return None, False


# Tracker label normalisation lives in ``donna.attention.noise``
# (see import above) so PING dedup and dashboard accept share one
# canonical alias table.


def _extract_target(spec: Any) -> float | None:
    """Best-effort pull of a numeric daily target from the spec.

    The schema does not encode targets explicitly today, so we look at
    a couple of soft signals (the description and any extractor prompt
    that mentions a number with a unit). Returns ``None`` when nothing
    is found — the rendered tracker will still work; it just won't have
    a target line.
    """
    if spec is None:
        return None
    import re

    text_parts: list[str] = []
    desc = getattr(spec, "description", None)
    if desc:
        text_parts.append(str(desc))
    extractor = getattr(spec, "extractor", None)
    if extractor is not None:
        prompt = getattr(extractor, "prompt", None)
        if prompt:
            text_parts.append(str(prompt))

    for chunk in text_parts:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(L|l|liters?|glasses|cups|ml)", chunk)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            unit = match.group(2).lower()
            if unit in {"ml"}:
                value = value / 1000.0
            return value
    return None


async def _recompose_after_accept(*, user_id: str) -> bool:
    """Trigger a dashboard recompose so the new state lands on next poll.

    Done here instead of inside the brain so the user sees the change
    immediately after tapping Accept, even if Donna is mid-turn or the
    user is not in chat. Best-effort: log + return False on failure.
    """
    try:
        from backend.dashboard.compose import compose_manifest
        from backend.dashboard.store import upsert_manifest
    except Exception:
        logger.exception("recompose_after_accept: imports failed")
        return False
    try:
        plan = await compose_manifest(
            user_id=user_id, trigger="attention_accepted"
        )
    except Exception:
        logger.exception(
            "recompose_after_accept: compose failed user=%s", user_id[:8]
        )
        return False
    if plan is None:
        return False
    try:
        await upsert_manifest(user_id, plan, trigger="attention_accepted")
        return True
    except Exception:
        logger.exception(
            "recompose_after_accept: upsert failed user=%s", user_id[:8]
        )
        return False
