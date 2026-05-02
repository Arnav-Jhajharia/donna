"""Capture-and-replay layer for integration-blocked turns.

When the user asks Donna to do something that needs an integration she
doesn't have yet ("summarize my gmail this week"), the model calls
``connect_integration`` and Donna sends a one-tap link. Today, after
the user taps and OAuth completes, the original ask dies on the floor —
the user has to re-prompt. This module fixes that.

Two functions:
- ``enqueue_intent(user_id, toolkits, intent)`` records the pending ask
  alongside the toolkits it needs.
- ``drain_for_toolkit(user_id, toolkit)`` is called from the OAuth
  watcher / webhook the moment a toolkit lands. It finds every pending
  intent whose required toolkits are now ALL connected, fires a
  proactive brain turn for each, and marks them ``status='fired'``.

Intents are short-lived. Anything older than 24 hours is treated as
expired — the user has likely moved on. The expires_at column is set
at enqueue so old rows are easy to sweep.

Drain is fire-and-forget from the watcher's perspective: if the brain
turn errors out, the row is marked ``status='failed'`` with
``last_error`` so the user gets a chance to re-prompt and we have
something to debug.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)


# How long a pending intent stays valid. Longer than the OAuth window
# (10min) but short enough that "user moved on" cases don't fire stale
# proactive turns the next morning.
_INTENT_TTL = timedelta(hours=24)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def enqueue_intent(
    user_id: str, toolkits: list[str], intent: str
) -> str | None:
    """Record a pending intent. Returns the row id, or None on failure.

    Idempotency: if an identical pending intent already exists (same user,
    same toolkit set, same intent text, status='pending'), we skip
    re-inserting and return the existing id. Stops the model from
    queueing 5 copies on a flaky-tap retry.
    """
    if not user_id or not intent or not toolkits:
        return None
    try:
        from backend.db.session import async_session
        from db.models import PendingIntegrationIntent
    except Exception:
        logger.exception("pending_intents.enqueue_intent: imports failed")
        return None

    norm_toolkits = sorted({str(t).strip() for t in toolkits if str(t).strip()})
    if not norm_toolkits:
        return None
    norm_intent = intent.strip()

    try:
        async with async_session() as session:
            existing = (
                await session.execute(
                    select(PendingIntegrationIntent).where(
                        PendingIntegrationIntent.user_id == user_id,
                        PendingIntegrationIntent.status == "pending",
                        PendingIntegrationIntent.intent == norm_intent,
                    )
                )
            ).scalars().all()
            for row in existing:
                # JSONB equality on list contents — compare canonicalised.
                if sorted(row.toolkits or []) == norm_toolkits:
                    return row.id

            now = _utcnow_naive()
            row = PendingIntegrationIntent(
                user_id=user_id,
                toolkits=norm_toolkits,
                intent=norm_intent,
                status="pending",
                created_at=now,
                expires_at=now + _INTENT_TTL,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info(
                "pending_intent enqueued: user=%s toolkits=%s id=%s",
                user_id[:8], norm_toolkits, row.id,
            )
            return row.id
    except Exception:
        logger.exception(
            "pending_intents.enqueue_intent: db write failed user=%s", user_id
        )
        return None


async def drain_for_toolkit(user_id: str, toolkit: str) -> int:
    """Fire any pending intents whose toolkit dependencies are all met.

    Called whenever an integration row flips to ``connected`` (from the
    OAuth watcher AND the webhook ingest path — both must call this so we
    don't drop the user no matter which lands first).

    Returns the count of intents fired. Errors per-intent are caught and
    logged; the caller never sees them.
    """
    if not user_id or not toolkit:
        return 0
    try:
        from backend.db.session import async_session
        from db.models import PendingIntegrationIntent
    except Exception:
        logger.exception("pending_intents.drain: imports failed")
        return 0

    norm_toolkit = toolkit.strip()
    fired_count = 0
    try:
        async with async_session() as session:
            now = _utcnow_naive()
            candidates = (
                await session.execute(
                    select(PendingIntegrationIntent).where(
                        PendingIntegrationIntent.user_id == user_id,
                        PendingIntegrationIntent.status == "pending",
                    )
                )
            ).scalars().all()
            ready: list[PendingIntegrationIntent] = []
            stale_ids: list[str] = []
            for row in candidates:
                if row.expires_at and row.expires_at < now:
                    stale_ids.append(row.id)
                    continue
                row_toolkits = list(row.toolkits or [])
                if norm_toolkit not in row_toolkits:
                    continue
                if await _all_connected(session, user_id, row_toolkits):
                    ready.append(row)

            for row in stale_ids:
                pass  # marked below in batch
            if stale_ids:
                for sid in stale_ids:
                    obj = await session.get(PendingIntegrationIntent, sid)
                    if obj:
                        obj.status = "expired"
                await session.commit()

            for row in ready:
                row.status = "firing"
                await session.commit()

        for row in ready:
            try:
                await _fire_proactive_turn(row.user_id, row.intent, row.id)
                async with async_session() as session:
                    obj = await session.get(PendingIntegrationIntent, row.id)
                    if obj:
                        obj.status = "fired"
                        obj.fired_at = _utcnow_naive()
                        await session.commit()
                fired_count += 1
            except Exception as exc:
                logger.exception(
                    "pending_intents.drain: fire failed user=%s id=%s",
                    user_id[:8], row.id,
                )
                async with async_session() as session:
                    obj = await session.get(PendingIntegrationIntent, row.id)
                    if obj:
                        obj.status = "failed"
                        obj.last_error = f"{type(exc).__name__}: {exc}"[:500]
                        await session.commit()
    except Exception:
        logger.exception(
            "pending_intents.drain: db read failed user=%s toolkit=%s",
            user_id, toolkit,
        )
    return fired_count


async def _all_connected(
    session: Any, user_id: str, toolkits: list[str]
) -> bool:
    """True iff every toolkit in the list is currently ``status=connected``
    in the integrations table. Reads in a single round-trip."""
    if not toolkits:
        return False
    try:
        from db.models import Integration
    except Exception:
        return False

    rows = (
        await session.execute(
            select(Integration).where(Integration.user_id == user_id)
        )
    ).scalars().all()

    connected_toolkits: set[str] = set()
    for r in rows:
        if r.status != "connected":
            continue
        # Map back to canonical toolkit slugs the model used. Google rows
        # are stored as provider="google", product="gmail|calendar|drive";
        # everything else as provider="composio", product=<slug>.
        if r.provider == "google":
            slug_map = {
                "gmail": "gmail",
                "calendar": "googlecalendar",
                "drive": "googledrive",
            }
            slug = slug_map.get(r.product, r.product)
            connected_toolkits.add(slug)
            # Also accept the friendly alias the model may have used.
            connected_toolkits.add(r.product)
        else:
            connected_toolkits.add(r.product)

    return all(tk in connected_toolkits for tk in toolkits)


async def _fire_proactive_turn(
    user_id: str, intent: str, intent_id: str
) -> None:
    """Re-fire the user's original ask as a proactive brain turn.

    The brain receives the intent text framed as the user's resumed
    message. ``mode='proactive'`` so the worker pipeline is used end-to-
    end (the same one that fires attentions). On the brain side the
    register stays reactive-feeling — Donna is just answering the ask
    that was paused for OAuth.
    """
    from sqlalchemy import select

    from backend.db.session import async_session
    from db.models import User
    from donna_runtime.brain import donna_turn
    from donna_runtime.config import DonnaAgentConfig

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        phone = getattr(user, "phone", None) if user else None
    if not phone:
        raise RuntimeError(f"no phone for user {user_id[:8]}")

    framed = (
        f"the user previously asked: {intent.strip()}\n"
        f"the integration they needed has just connected. "
        f"answer the ask now in donna's voice — do not announce that "
        f"you're resuming, do not mention the integration by name, "
        f"just answer."
    )
    cfg = DonnaAgentConfig(
        mode="proactive",
        user_id=user_id,
        user_phone=phone,
        target_phone=phone,
        stateless_sessions=True,
    )
    state = {
        "user_id": user_id,
        "raw_input": framed,
        "user_message": framed,
        "phone": phone,
        "trigger": {
            "source": "integration_resume",
            "intent_id": intent_id,
        },
    }
    await donna_turn(state, cfg)
