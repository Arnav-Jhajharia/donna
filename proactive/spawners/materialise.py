"""Spawner-side materialisation: turn InferredIntent into Attention.

Routes intents through the existing pipeline:

- HIGH → ``donna_runtime.tools._create_and_queue_attention`` with
  ``origin="donna"``. The same path ``attend(origin="donna")`` uses.
  Result: LIVE attention, DonnaSchedule fire queued, dispatcher
  picks it up at fire time.
- MEDIUM → ``create_attention(auto_live=False)``, then patch status
  to SHADOW + origin SHADOW_INFERRED. The existing promote cycle in
  ``donna.attention.promote`` ticks it and graduates to OFFERED if
  signal warrants. Same shape as the existing CalendarRecurrenceProposer.
- LOW → drop, no row written.

All errors are logged and swallowed. Spawners are best-effort and
must not break the caller (calendar ingest, log_observation, daily
sweep).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from proactive.spawners.dedup import SpawnerDedupLedger
from proactive.spawners.shape import InferredIntent, SpawnConfidence

logger = logging.getLogger(__name__)


async def materialise_intents(
    intents: Iterable[InferredIntent],
    *,
    user_id: str,
    ledger: SpawnerDedupLedger | None = None,
) -> list[str]:
    """Materialise each intent through the appropriate path.

    Returns the list of created ``attention_id`` strings (HIGH path)
    plus shadow IDs (MEDIUM path). LOW intents and dedup hits return
    no id. Order matches the input order.
    """
    ledger = ledger or SpawnerDedupLedger()
    out: list[str] = []
    for intent in intents:
        try:
            attention_id = await _materialise_one(intent, user_id=user_id, ledger=ledger)
        except Exception:
            logger.exception(
                "spawner: materialise failed dedup_key=%s template=%s",
                intent.dedup_key,
                intent.template_id,
            )
            continue
        if attention_id:
            out.append(attention_id)
    return out


async def _materialise_one(
    intent: InferredIntent,
    *,
    user_id: str,
    ledger: SpawnerDedupLedger,
) -> str | None:
    if intent.confidence is SpawnConfidence.LOW:
        return None
    if ledger.has_spawned(intent.dedup_key):
        logger.info(
            "spawner: dedup hit, skipping dedup_key=%s template=%s",
            intent.dedup_key,
            intent.template_id,
        )
        return None

    if intent.confidence is SpawnConfidence.HIGH:
        attention_id = await _spawn_live(intent, user_id=user_id)
    else:
        attention_id = await _spawn_shadow(intent, user_id=user_id)

    if attention_id:
        ledger.record(intent.dedup_key, attention_id)
    return attention_id


async def _spawn_live(intent: InferredIntent, *, user_id: str) -> str | None:
    """LIVE path — same machinery as ``attend(origin='donna')``."""
    from donna_runtime.tools import _create_and_queue_attention

    label = f"spawner:{intent.template_id}"
    result = await _create_and_queue_attention(
        intent=intent.text,
        user_id=user_id,
        origin="donna",
        label=label,
    )
    status = result.get("status")
    if status in ("ok", "reused"):
        return str(result.get("attention_id") or "") or None
    if status == "past_trigger":
        logger.info(
            "spawner: dropped past-trigger intent template=%s text=%r",
            intent.template_id,
            intent.text,
        )
        return None
    logger.warning(
        "spawner: LIVE materialise failed status=%s reason=%s template=%s",
        status,
        result.get("reason"),
        intent.template_id,
    )
    return None


async def _spawn_shadow(intent: InferredIntent, *, user_id: str) -> str | None:
    """SHADOW path — author the spec then save as SHADOW directly.

    Mirrors what ``propose_and_shadow`` does for proposer candidates.
    The promote cycle picks SHADOW rows up on its next tick.
    """
    try:
        from donna.attention.schema import (
            Attention,
            AttentionOrigin,
            AttentionStatus,
            ShadowState,
        )
        from donna.attention.harness import run_attention_pipeline
        from donna.attention.normalize import UserContext, load_user_timezone
        from donna.attention.store import AttentionStore
        from donna.attention.tools import _coerce_uuid
    except Exception:
        logger.exception("spawner: shadow imports unavailable")
        return None

    try:
        tz = await load_user_timezone(user_id)
        ctx = (
            UserContext(user_id=user_id, user_tz=tz)
            if tz
            else UserContext(user_id=user_id)
        )
        pipeline = await run_attention_pipeline(intent.text, ctx)
    except Exception:
        logger.exception(
            "spawner: shadow author failed template=%s", intent.template_id
        )
        return None

    try:
        attention = Attention(
            user_id=_coerce_uuid(user_id),
            spec=pipeline.authored.spec,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=AttentionStatus.SHADOW,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState(priority="medium"),
        )
        store = AttentionStore()
        store.save(attention)
        return str(attention.id)
    except Exception:
        logger.exception(
            "spawner: shadow save failed template=%s", intent.template_id
        )
        return None
